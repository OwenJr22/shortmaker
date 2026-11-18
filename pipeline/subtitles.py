"""Génération de sous-titres animés au format ASS (rendus ensuite par ffmpeg/libass)."""
import re

W, H = 1080, 1920
FONT = "Poppins"

STYLES = {
    "karaoke": {"label": "Karaoké (mot surligné)", "max_words": 3, "size": 100, "outline": 7},
    "hormozi": {"label": "Hormozi (gros mots qui pop)", "max_words": 2, "size": 135, "outline": 9},
    "neon":    {"label": "Néon (mot lumineux)", "max_words": 4, "size": 84, "outline": 4},
    "minimal": {"label": "Sobre (phrases sur fond)", "max_words": 6, "size": 70, "outline": 0},
}

POSITIONS = {"bas": 0.72, "milieu": 0.52, "haut": 0.25}


def _ass_color(hex_color, alpha="00"):
    """#RRGGBB -> &HAABBGGRR (format ASS)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFE600"
    return f"&H{alpha}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ts(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(text):
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _group(words, max_words):
    """Regroupe les mots en petits blocs (coupure sur ponctuation, pause ou nombre max)."""
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        ends_sentence = bool(re.search(r"[.!?…,;:]$", w["word"]))
        long_pause = nxt is not None and nxt["start"] - w["end"] > 0.6
        if len(cur) >= max_words or ends_sentence or long_pause or nxt is None:
            groups.append(cur)
            cur = []
    return groups


def build_ass(words, clip_start, clip_end, style="karaoke", highlight="#FFE600",
              uppercase=True, position="bas", hook="", hook_seconds=3.0):
    """words : mots absolus (secondes dans la vidéo source). Renvoie le contenu du fichier .ass."""
    cfg = STYLES.get(style, STYLES["karaoke"])
    hl = _ass_color(highlight)
    y = int(H * POSITIONS.get(position, 0.72))
    dur = clip_end - clip_start

    # Mots relatifs au début du clip, nettoyés
    rel = []
    for w in words:
        s, e = max(0.0, w["start"] - clip_start), min(dur, w["end"] - clip_start)
        txt = _clean(w["word"]).strip()
        if e > s and txt:
            rel.append({"start": s, "end": e, "word": txt.upper() if uppercase else txt})

    if style == "minimal":
        primary, outline_c, back, border_style = "&H00FFFFFF", "&H80000000", "&H80000000", 3
    else:
        primary, outline_c, back, border_style = "&H00FFFFFF", "&H00000000", "&H96000000", 1

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{FONT},{cfg['size']},{primary},&H000000FF,{outline_c},{back},-1,0,0,0,100,100,1,0,{border_style},{cfg['outline'] or 18},3,5,60,60,0,1
Style: Hook,{FONT},78,&H00111111,&H000000FF,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,22,0,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if hook:
        lines.append(
            f"Dialogue: 1,{_ts(0.15)},{_ts(min(hook_seconds, dur))},Hook,,0,0,0,,"
            f"{{\\an5\\pos({W // 2},{int(H * 0.16)})\\fad(150,250)"
            f"\\fscx80\\fscy80\\t(0,180,\\fscx100\\fscy100)}}{_clean(hook)}"
        )

    groups = _group(rel, cfg["max_words"])
    for gi, g in enumerate(groups):
        nxt_start = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else dur
        g_end = min(nxt_start, g[-1]["end"] + 0.35)
        pos = f"\\an5\\pos({W // 2},{y})"

        if style == "hormozi":
            text = " ".join(w["word"] for w in g)
            colored = any(len(re.sub(r"\W", "", w["word"])) >= 6 for w in g) or gi % 3 == 0
            color = f"\\c{hl}" if colored else ""
            anim = "\\fscx70\\fscy70\\t(0,90,\\fscx110\\fscy110)\\t(90,160,\\fscx100\\fscy100)"
            lines.append(f"Dialogue: 0,{_ts(g[0]['start'])},{_ts(g_end)},Sub,,0,0,0,,"
                         f"{{{pos}{anim}{color}\\blur0.6}}{text}")
            continue

        if style == "minimal":
            text = " ".join(w["word"] for w in g)
            lines.append(f"Dialogue: 0,{_ts(g[0]['start'])},{_ts(g_end)},Sub,,0,0,0,,"
                         f"{{{pos}\\fad(80,80)}}{text}")
            continue

        # karaoke et neon : un évènement par mot, le mot prononcé est mis en avant
        for i, w in enumerate(g):
            start = w["start"] if i else g[0]["start"]
            end = g[i + 1]["start"] if i + 1 < len(g) else g_end
            if end <= start:
                continue
            parts = []
            for j, o in enumerate(g):
                if j == i and style == "karaoke":
                    parts.append(f"{{\\c{hl}\\t(0,70,\\fscx118\\fscy118)\\t(70,150,\\fscx110\\fscy110)}}"
                                 f"{o['word']}{{\\c&H00FFFFFF&\\fscx100\\fscy100}}")
                elif j == i and style == "neon":
                    parts.append(f"{{\\c&H00FFFFFF&\\3c{hl}\\bord6\\blur5}}"
                                 f"{o['word']}{{\\3c&H00000000&\\bord4\\blur0.6}}")
                else:
                    parts.append(o["word"])
            intro = "\\fscx92\\fscy92\\t(0,80,\\fscx100\\fscy100)" if i == 0 else ""
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Sub,,0,0,0,,"
                         f"{{{pos}{intro}\\blur0.6}}" + " ".join(parts))

    return header + "\n".join(lines) + "\n"
