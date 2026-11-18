"""Transcription locale avec faster-whisper, minutage mot par mot."""
from pathlib import Path

from .utils import PipelineError, run

_MODEL_CACHE = {}


def _load_model(size):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise PipelineError("faster-whisper n'est pas installé (pip install -r requirements.txt).") from exc

    if size not in _MODEL_CACHE:
        device, compute = "cpu", "int8"
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                device, compute = "cuda", "float16"
        except Exception:
            pass
        _MODEL_CACHE[size] = WhisperModel(size, device=device, compute_type=compute)
    return _MODEL_CACHE[size]


def transcribe(video_path, work_dir, model_size="small", language=None, progress=None):
    """Renvoie {"language", "segments": [{start, end, text, words: [{start, end, word}]}]}."""
    audio = Path(work_dir) / "audio.wav"
    run(["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", str(audio)],
        "l'extraction audio")

    model = _load_model(model_size)
    segments_iter, info = model.transcribe(
        str(audio),
        language=language or None,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )
    duration = info.duration or 1
    segments = []
    for seg in segments_iter:
        words = [
            {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
            for w in (seg.words or []) if w.word.strip()
        ]
        segments.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "words": words,
        })
        if progress:
            progress(min(seg.end / duration, 1.0))
    audio.unlink(missing_ok=True)
    return {"language": info.language, "segments": segments}


def words_in_range(transcript, start, end):
    """Tous les mots entre start et end (en secondes)."""
    out = []
    for seg in transcript.get("segments", []):
        if seg["end"] < start or seg["start"] > end:
            continue
        for w in seg.get("words", []):
            if w["end"] > start and w["start"] < end:
                out.append(w)
    return out
