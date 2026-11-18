"""Suggestion des moments forts avec l'API Claude (Anthropic)."""
import json
import os
import re
import urllib.error
import urllib.request

from .utils import PipelineError, fmt_time

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")

PROMPT = """Tu es un monteur expert en vidéos courtes virales (TikTok, Reels, Shorts).
Voici la transcription horodatée d'une vidéo ({duration}). Chaque ligne commence par [mm:ss.s].

Trouve les {count} meilleurs passages à transformer en shorts autonomes :
- durée entre {min_len} et {max_len} secondes ;
- ils doivent commencer par une accroche forte (question, affirmation choc, tension) ;
- ils doivent se comprendre sans le reste de la vidéo et se terminer sur une phrase complète ;
- ne pas se chevaucher.

Réponds UNIQUEMENT avec un tableau JSON, sans texte autour, au format :
[{{"start": 12.4, "end": 51.0, "title": "titre court accrocheur", "hook": "texte d'accroche à afficher en haut (max 8 mots)", "reason": "pourquoi ce passage marche", "score": 87}}]
"start" et "end" sont en secondes. "score" est la note de potentiel viral sur 100.
{extra}
TRANSCRIPTION :
{transcript}"""


def _transcript_lines(transcript):
    return "\n".join(f"[{fmt_time(s['start'])}] {s['text']}" for s in transcript["segments"])


def _snap(clips, transcript, duration):
    """Cale début et fin sur des débuts/fins de mots pour ne pas couper une syllabe."""
    words = [w for s in transcript["segments"] for w in s.get("words", [])]
    out = []
    for c in clips:
        try:
            start, end = float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if words:
            start = min(words, key=lambda w: abs(w["start"] - start))["start"]
            end = min(words, key=lambda w: abs(w["end"] - end))["end"]
        start = max(0.0, start - 0.15)
        end = min(duration or end + 0.3, end + 0.3)
        if end - start < 3:
            continue
        out.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "title": str(c.get("title", "")).strip()[:100],
            "hook": str(c.get("hook", "")).strip()[:80],
            "reason": str(c.get("reason", "")).strip(),
            "score": int(c.get("score", 0) or 0),
        })
    return sorted(out, key=lambda c: -c["score"])


def suggest_clips(transcript, duration, api_key, count=5, min_len=20, max_len=60,
                  instructions="", model=None):
    if not api_key:
        raise PipelineError("Aucune clé API Claude configurée (bouton ⚙️ Réglages).")
    if not transcript.get("segments"):
        raise PipelineError("La transcription est vide : rien à analyser.")

    extra = f"\nConsignes supplémentaires du créateur : {instructions}\n" if instructions else ""
    prompt = PROMPT.format(
        duration=fmt_time(duration), count=count, min_len=min_len, max_len=max_len,
        extra=extra, transcript=_transcript_lines(transcript),
    )
    body = json.dumps({
        "model": model or DEFAULT_MODEL,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise PipelineError(f"Erreur de l'API Claude ({exc.code}) : {detail}") from exc
    except urllib.error.URLError as exc:
        raise PipelineError(f"Impossible de joindre l'API Claude : {exc.reason}") from exc

    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        raise PipelineError("Réponse de l'IA illisible, réessaie.")
    try:
        clips = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise PipelineError("Réponse de l'IA mal formée, réessaie.") from exc
    return _snap(clips, transcript, duration)
