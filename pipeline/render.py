"""Rendu d'un short : découpe + recadrage 9:16 + sous-titres animés (+ barre de progression)."""
import shutil
import sys
from pathlib import Path

from . import reframe
from .subtitles import build_ass
from .transcribe import words_in_range
from .utils import PipelineError, probe

OUT_W, OUT_H = 1080, 1920
FONTS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "fonts"


def _video_filter(mode, info, keys, dur, progress_bar, bar_color, ass_name):
    w, h = info["width"], info["height"]
    vertical = w / h <= 9 / 16 + 0.01

    if vertical:
        base = (f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
                f"crop={OUT_W}:{OUT_H},setsar=1[v0]")
    elif mode == "blur":
        base = (f"[0:v]split[a][b];"
                f"[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
                f"crop={OUT_W}:{OUT_H},boxblur=25:3,eq=brightness=-0.08[bg];"
                f"[b]scale={OUT_W}:-2[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v0]")
    else:
        cw = reframe.crop_width(w, h)
        if mode == "face" and keys:
            x = reframe.x_expression(keys)
        else:
            x = f"{(w - cw) / 2:.1f}"
        base = f"[0:v]crop={cw}:{h - h % 2}:'{x}':0,scale={OUT_W}:{OUT_H},setsar=1[v0]"

    chain = base + f";[v0]ass={ass_name}:fontsdir=fonts"
    if progress_bar:
        color = bar_color.lstrip("#")
        chain += (f",drawbox=x=0:y=ih-16:w='iw*min(t/{dur:.3f}\\,1)':h=16:"
                  f"color=0x{color}@0.95:t=fill")
    return chain + "[vout]"


def render_clip(source, transcript, clip, out_path, options, work_dir):
    """clip : {start, end, hook}. options : style, highlight, uppercase, position,
    reframe (face|center|blur), progress_bar, show_hook."""
    start, end = float(clip["start"]), float(clip["end"])
    if end <= start:
        raise PipelineError("La fin du clip doit être après le début.")
    dur = end - start
    info = probe(source)
    work_dir = Path(work_dir)
    out_path = Path(out_path)

    # Les polices sont copiées à côté pour éviter les soucis de chemins (Windows notamment)
    fonts_local = work_dir / "fonts"
    if not fonts_local.exists():
        shutil.copytree(FONTS_DIR, fonts_local)

    words = words_in_range(transcript, start, end)
    ass = build_ass(
        words, start, end,
        style=options.get("style", "karaoke"),
        highlight=options.get("highlight", "#FFE600"),
        uppercase=options.get("uppercase", True),
        position=options.get("position", "bas"),
        hook=(clip.get("hook") or "") if options.get("show_hook", True) else "",
    )
    ass_name = f"sub_{out_path.stem}.ass"
    (work_dir / ass_name).write_text(ass, encoding="utf-8")

    mode = options.get("reframe", "face")
    keys = None
    if mode == "face" and info["width"] / info["height"] > 9 / 16 + 0.01:
        keys = reframe.track_faces(source, start, end, info["width"], info["height"])

    vf = _video_filter(mode, info, keys, dur, options.get("progress_bar", True),
                       options.get("highlight", "#FFE600"), ass_name)
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(Path(source).resolve()),
           "-t", f"{dur:.3f}", "-filter_complex", vf, "-map", "[vout]"]
    if info["has_audio"]:
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-r", "30", "-movflags", "+faststart", str(out_path.resolve())]

    import subprocess
    proc = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise PipelineError(f"Échec du rendu vidéo :\n{tail}")
    return {"face_tracking": bool(keys), "duration": round(dur, 2)}
