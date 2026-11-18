"""Téléchargement d'une vidéo YouTube, Twitch, Kick… (tout site supporté par yt-dlp)."""
from pathlib import Path

from .utils import PipelineError


def download(url, dest_dir, progress=None, cookies=None, start=None, end=None):
    """Télécharge la vidéo en MP4 (1080p max) et renvoie (chemin, titre).
    start/end (secondes) : ne télécharge que cet extrait (pratique pour les VOD de plusieurs heures)."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise PipelineError("yt-dlp n'est pas installé (pip install -r requirements.txt).") from exc

    dest_dir = Path(dest_dir)

    def hook(d):
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress(d.get("downloaded_bytes", 0) / total)

    opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }
    if cookies:
        opts["cookiefile"] = str(cookies)
    if start is not None or end is not None:
        from yt_dlp.utils import download_range_func
        opts["download_ranges"] = download_range_func(None, [(start or 0, end or float("inf"))])
        opts["force_keyframes_at_cuts"] = True
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:  # yt-dlp lève des erreurs variées
        raise PipelineError(
            f"Téléchargement impossible : {exc}\n"
            "Astuces : si YouTube demande de confirmer que tu n'es pas un robot, ajoute ton fichier "
            "cookies.txt dans ⚙️ Réglages. Mets aussi l'app à jour si le site a changé, "
            "ou importe directement le fichier vidéo."
        ) from exc

    files = sorted(dest_dir.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
    files = [f for f in files if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")]
    if not files:
        raise PipelineError("Le fichier téléchargé est introuvable.")
    title = info.get("title") or "Vidéo"
    if start is not None or end is not None:
        from .utils import fmt_time
        title += f" ({fmt_time(start or 0)} → {fmt_time(end) if end else 'fin'})"
    return files[0], title
