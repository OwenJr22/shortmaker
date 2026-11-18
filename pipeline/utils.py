"""Petits utilitaires partagés : ffmpeg, ffprobe, temps."""
import json
import shutil
import subprocess


class PipelineError(Exception):
    pass


def check_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise PipelineError(
                f"{tool} est introuvable. Installe FFmpeg (voir README) puis relance l'app."
            )


def run(cmd, what="commande"):
    """Lance une commande et lève une erreur lisible si elle échoue."""
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise PipelineError(f"Échec de {what} :\n{tail}")
    return proc


def probe(path):
    """Renvoie largeur, hauteur, fps et durée de la vidéo."""
    out = run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        "ffprobe",
    ).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if video is None:
        raise PipelineError("Aucune piste vidéo trouvée dans le fichier.")
    num, den = (video.get("avg_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    has_audio = any(s.get("codec_type") == "audio" for s in data["streams"])
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": fps or 30.0,
        "duration": float(data["format"].get("duration", 0)),
        "has_audio": has_audio,
    }


def fmt_time(seconds):
    seconds = max(0.0, float(seconds))
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:04.1f}"
