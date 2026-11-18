"""ShortMaker : transforme une vidéo longue en shorts sous-titrés, en local.

Lancement :  python app.py   puis ouvrir http://127.0.0.1:5050
"""
import hashlib
import hmac
import json
import os
import shutil
import socket
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, request, send_from_directory, session

from pipeline.download import download
from pipeline.render import render_clip
from pipeline.subtitles import POSITIONS, STYLES
from pipeline.suggest import suggest_clips
from pipeline.transcribe import transcribe
from pipeline.utils import PipelineError, check_ffmpeg, probe

# En mode .exe (PyInstaller), les ressources sont dans _MEIPASS et les données à côté du .exe
FROZEN = getattr(sys, "frozen", False)
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else ROOT
for _ff in (APP_DIR / "ffmpeg", ROOT / "ffmpeg"):  # FFmpeg fourni avec l'app
    if (_ff / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")).exists():
        os.environ["PATH"] = str(_ff) + os.pathsep + os.environ.get("PATH", "")
        break
IS_MAC_APP = FROZEN and sys.platform == "darwin"
# Sur Mac, une app téléchargée tourne depuis un emplacement en lecture seule :
# les projets et les shorts vont donc dans le dossier Vidéos (~/Movies/ShortMaker).
_default_data = Path.home() / "Movies" / "ShortMaker" if IS_MAC_APP else APP_DIR / "data"
DATA = Path(os.environ.get("DATA_DIR") or _default_data)
DATA.mkdir(parents=True, exist_ok=True)
if sys.stdout is None or sys.stderr is None:  # app Mac sans fenêtre de terminal : on écrit dans un journal
    _log = open(DATA / "journal.txt", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log
for _stream in (sys.stdout, sys.stderr):  # évite les plantages d'accents/emojis dans la console Windows
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
SETTINGS_FILE = DATA / "settings.json"
PORT = int(os.environ.get("PORT", 5050))
HOST = os.environ.get("HOST", "127.0.0.1")
ONLINE = HOST not in ("127.0.0.1", "localhost")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY") or hashlib.sha256(
    ("shortmaker:" + APP_PASSWORD + str(DATA)).encode()).hexdigest()
if os.environ.get("HTTPS_COOKIES"):  # en ligne (https) : le cookie marche aussi dans un iframe
    app.config.update(SESSION_COOKIE_SAMESITE="None", SESSION_COOKIE_SECURE=True)
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30
_locks = {}
_global_lock = threading.Lock()


# --------------------------------------------------------------------------- stockage

def _lock(pid):
    with _global_lock:
        return _locks.setdefault(pid, threading.Lock())


def pdir(pid):
    if not pid.isalnum():
        abort(404)
    return DATA / pid


def load(pid):
    f = pdir(pid) / "project.json"
    if not f.exists():
        abort(404)
    return json.loads(f.read_text(encoding="utf-8"))


def save(project):
    f = pdir(project["id"]) / "project.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(f)


def update(pid, **fields):
    with _lock(pid):
        p = load(pid)
        p.update(fields)
        save(p)
        return p


def settings():
    s = {"api_key": "", "whisper_model": os.environ.get("WHISPER_MODEL", "small"), "language": "fr"}
    if SETTINGS_FILE.exists():
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    if not s["api_key"]:
        s["api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
    return s


def cookies_file():
    f = DATA / "cookies.txt"
    if not f.exists() and os.environ.get("YTDLP_COOKIES"):
        f.write_text(os.environ["YTDLP_COOKIES"], encoding="utf-8")
    return f if f.exists() else None


def run_bg(target, *args):
    threading.Thread(target=target, args=args, daemon=True).start()


def set_task(pid, kind=None, progress=0.0, message="", error=None):
    task = None if kind is None else {"kind": kind, "progress": round(progress, 3),
                                      "message": message, "error": error}
    update(pid, task=task)


# --------------------------------------------------------------------------- tâches de fond

def job_import(pid, url, start=None, end=None):
    d = pdir(pid)
    try:
        if url:
            update(pid, status="downloading")
            set_task(pid, "import", 0, "Téléchargement de la vidéo…")
            last = [0.0]

            def prog(x):
                if x - last[0] > 0.02:
                    last[0] = x
                    set_task(pid, "import", x * 0.3, "Téléchargement de la vidéo…")
            path, title = download(url, d, prog, cookies_file(), start, end)
            update(pid, source=path.name, title=title)

        p = load(pid)
        info = probe(d / p["source"])
        update(pid, status="transcribing", duration=info["duration"],
               width=info["width"], height=info["height"])
        if not info["has_audio"]:
            raise PipelineError("La vidéo n'a pas de son : impossible de transcrire.")

        s = settings()
        set_task(pid, "import", 0.3, f"Transcription (Whisper « {s['whisper_model']} »)… "
                                     "le premier lancement télécharge le modèle.")
        last = [0.0]

        def tprog(x):
            if x - last[0] > 0.02:
                last[0] = x
                set_task(pid, "import", 0.3 + x * 0.7, f"Transcription… {int(x * 100)} %")
        tr = transcribe(d / p["source"], d, s["whisper_model"], s["language"] or None, tprog)
        (d / "transcript.json").write_text(json.dumps(tr, ensure_ascii=False), encoding="utf-8")
        update(pid, status="ready", language=tr["language"])
        set_task(pid)
    except Exception as exc:
        traceback.print_exc()
        update(pid, status="error", error=str(exc))
        set_task(pid)


def job_suggest(pid, params):
    try:
        set_task(pid, "suggest", 0.2, "L'IA analyse la transcription…")
        p = load(pid)
        tr = json.loads((pdir(pid) / "transcript.json").read_text(encoding="utf-8"))
        found = suggest_clips(
            tr, p.get("duration", 0), settings()["api_key"],
            count=int(params.get("count", 5)), min_len=int(params.get("min_len", 20)),
            max_len=int(params.get("max_len", 60)), instructions=params.get("instructions", ""),
        )
        with _lock(pid):
            p = load(pid)
            for c in found:
                c.update(id=uuid.uuid4().hex[:8], source="ia")
            p["clips"] = [c for c in p.get("clips", []) if c.get("source") != "ia" or c.get("output")] + found
            save(p)
        set_task(pid)
    except Exception as exc:
        traceback.print_exc()
        set_task(pid, "suggest", 0, "", error=str(exc))


def job_render(pid, clip_ids, options):
    d = pdir(pid)
    out_dir = d / "clips"
    out_dir.mkdir(exist_ok=True)
    try:
        tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
        p = load(pid)
        todo = [c for c in p.get("clips", []) if c["id"] in clip_ids]
        for i, clip in enumerate(todo, 1):
            set_task(pid, "render", (i - 1) / len(todo), f"Rendu du short {i}/{len(todo)}…")
            name = f"short_{clip['id']}_{int(time.time())}.mp4"
            render_clip(d / p["source"], tr, clip, out_dir / name, options, d)
            with _lock(pid):
                p2 = load(pid)
                for c in p2["clips"]:
                    if c["id"] == clip["id"]:
                        if c.get("output"):
                            (out_dir / c["output"]).unlink(missing_ok=True)
                        c["output"] = name
                        c["rendered_with"] = options
                save(p2)
        set_task(pid)
    except Exception as exc:
        traceback.print_exc()
        set_task(pid, "render", 0, "", error=str(exc))


# --------------------------------------------------------------------------- mot de passe

LOGIN_PAGE = """<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ShortMaker</title>
<style>body{margin:0;display:grid;place-items:center;height:100vh;background:#0e0f13;color:#e9ebf1;
font:15px system-ui,sans-serif}form{background:#16181f;border:1px solid #2a2e3a;border-radius:14px;
padding:28px;width:min(340px,90vw);display:flex;flex-direction:column;gap:12px}h1{margin:0 0 6px;font-size:20px}
h1 span{color:#ffd23f}input,button{font:inherit;padding:10px 12px;border-radius:8px;border:1px solid #2a2e3a;
background:#0f1117;color:inherit}button{background:#ffd23f;color:#111;border:0;font-weight:650;cursor:pointer}
.e{color:#ff8fa3;font-size:13px}</style></head><body><form method="post">
<h1>Short<span>Maker</span></h1><input type="password" name="password" placeholder="Mot de passe" autofocus>
%ERR%<button>Entrer</button></form></body></html>"""


@app.before_request
def require_login():
    if not APP_PASSWORD or request.endpoint == "login" or session.get("ok"):
        return None
    if request.path.startswith(("/api/", "/media/")):
        return jsonify({"error": "Non connecté"}), 401
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PASSWORD:
        return redirect("/")
    err = ""
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("password", "").encode(), APP_PASSWORD.encode()):
            session["ok"] = True
            session.permanent = True
            return redirect("/")
        time.sleep(1.5)  # ralentit les essais au hasard
        err = '<div class="e">Mot de passe incorrect.</div>'
    return LOGIN_PAGE.replace("%ERR%", err)


@app.post("/api/cookies")
def upload_cookies():
    """Fichier cookies.txt (YouTube) pour éviter les blocages « confirme que tu n'es pas un robot »."""
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Aucun fichier."}), 400
    content = f.read().decode("utf-8", errors="replace")
    if "youtube.com" not in content:
        return jsonify({"error": "Ce fichier ne contient pas de cookies YouTube."}), 400
    (DATA / "cookies.txt").write_text(content, encoding="utf-8")
    return get_config()


@app.delete("/api/cookies")
def delete_cookies():
    (DATA / "cookies.txt").unlink(missing_ok=True)
    return get_config()


# --------------------------------------------------------------------------- API

@app.get("/")
def index():
    return send_from_directory(ROOT / "static", "index.html")


@app.get("/api/config")
def get_config():
    s = settings()
    key = s["api_key"]
    return jsonify({
        "has_api_key": bool(key),
        "api_key_hint": (key[:7] + "…" + key[-4:]) if len(key) > 12 else "",
        "whisper_model": s["whisper_model"],
        "language": s["language"],
        "styles": {k: v["label"] for k, v in STYLES.items()},
        "positions": list(POSITIONS),
        "has_cookies": (DATA / "cookies.txt").exists() or bool(os.environ.get("YTDLP_COOKIES")),
        "online": ONLINE,
        "can_quit": FROZEN and not ONLINE,
        "data_dir": str(DATA),
    })


@app.post("/api/config")
def set_config():
    body = request.get_json(force=True)
    s = settings() if SETTINGS_FILE.exists() else {"api_key": "", "whisper_model": "small", "language": "fr"}
    for k in ("api_key", "whisper_model", "language"):
        if k in body and (k != "api_key" or body[k]):
            s[k] = body[k].strip()
    SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
    return get_config()


@app.get("/api/projects")
def list_projects():
    out = []
    for f in DATA.glob("*/project.json"):
        p = json.loads(f.read_text(encoding="utf-8"))
        out.append({k: p.get(k) for k in ("id", "title", "status", "created", "duration")})
    return jsonify(sorted(out, key=lambda p: -(p["created"] or 0)))


@app.post("/api/projects")
def create_project():
    pid = uuid.uuid4().hex[:12]
    d = pdir(pid)
    d.mkdir(parents=True)
    project = {"id": pid, "created": time.time(), "status": "new", "clips": [],
               "title": "Nouvelle vidéo", "task": None}
    url = None
    if "file" in request.files:
        f = request.files["file"]
        ext = Path(f.filename or "video.mp4").suffix.lower() or ".mp4"
        f.save(d / f"source{ext}")
        project.update(source=f"source{ext}", title=Path(f.filename or "Vidéo").stem)
    else:
        body = request.get_json(force=True) or {}
        url = body.get("url", "").strip()
        rng = [body.get("start"), body.get("end")]
        rng = [float(x) if x not in (None, "") else None for x in rng]
        if rng[0] is not None and rng[1] is not None and rng[1] <= rng[0]:
            shutil.rmtree(d)
            return jsonify({"error": "La fin de l'extrait doit être après le début."}), 400
        project["range"] = rng
        if not url:
            shutil.rmtree(d)
            return jsonify({"error": "Donne un lien ou un fichier."}), 400
        project["url"] = url
    save(project)
    run_bg(job_import, pid, url, *(project.get("range") or [None, None]))
    return jsonify(project)


@app.get("/api/projects/<pid>")
def get_project(pid):
    p = load(pid)
    tf = pdir(pid) / "transcript.json"
    if request.args.get("transcript") and tf.exists():
        p["transcript"] = json.loads(tf.read_text(encoding="utf-8"))
    return jsonify(p)


@app.delete("/api/projects/<pid>")
def delete_project(pid):
    load(pid)
    shutil.rmtree(pdir(pid), ignore_errors=True)
    return jsonify({"ok": True})


@app.post("/api/projects/<pid>/retry")
def retry(pid):
    p = load(pid)
    update(pid, status="new", error=None)
    run_bg(job_import, pid, p.get("url") if not p.get("source") else None,
           *(p.get("range") or [None, None]))
    return jsonify({"ok": True})


@app.put("/api/projects/<pid>/clips")
def save_clips(pid):
    clips = request.get_json(force=True).get("clips", [])
    with _lock(pid):
        p = load(pid)
        old = {c["id"]: c for c in p.get("clips", [])}
        cleaned = []
        for c in clips:
            cid = c.get("id") or uuid.uuid4().hex[:8]
            base = old.get(cid, {"id": cid, "source": "manuel"})
            base.update({k: c[k] for k in ("start", "end", "title", "hook") if k in c})
            base["start"], base["end"] = float(base["start"]), float(base["end"])
            cleaned.append(base)
        for cid, c in old.items():  # supprime les fichiers des clips retirés
            if cid not in {x["id"] for x in cleaned} and c.get("output"):
                (pdir(pid) / "clips" / c["output"]).unlink(missing_ok=True)
        p["clips"] = cleaned
        save(p)
    return jsonify(p)


def _busy(p):
    t = p.get("task")
    return t and not t.get("error")


@app.post("/api/projects/<pid>/suggest")
def suggest(pid):
    p = load(pid)
    if p["status"] != "ready" or _busy(p):
        return jsonify({"error": "Le projet n'est pas prêt ou une tâche est en cours."}), 409
    set_task(pid, "suggest", 0.05, "L'IA analyse la transcription…")
    run_bg(job_suggest, pid, request.get_json(force=True) or {})
    return jsonify({"ok": True})


@app.post("/api/projects/<pid>/render")
def render(pid):
    p = load(pid)
    if p["status"] != "ready" or _busy(p):
        return jsonify({"error": "Le projet n'est pas prêt ou une tâche est en cours."}), 409
    body = request.get_json(force=True)
    ids = body.get("clip_ids") or [c["id"] for c in p.get("clips", [])]
    if not ids:
        return jsonify({"error": "Aucun clip à rendre."}), 400
    set_task(pid, "render", 0, "Préparation du rendu…")
    run_bg(job_render, pid, ids, body.get("options", {}))
    return jsonify({"ok": True})


@app.post("/api/projects/<pid>/dismiss")
def dismiss(pid):
    set_task(pid)
    return jsonify({"ok": True})


@app.post("/api/quit")
def quit_app():
    if ONLINE:
        abort(404)
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return jsonify({"ok": True})


@app.post("/api/reveal")
def reveal():
    """Ouvre le dossier des shorts dans le Finder / l'Explorateur."""
    if ONLINE:
        abort(404)
    import subprocess
    target = str(DATA)
    if sys.platform == "darwin":
        subprocess.Popen(["open", target])
    elif os.name == "nt":
        os.startfile(target)  # noqa
    else:
        subprocess.Popen(["xdg-open", target])
    return jsonify({"ok": True})


@app.get("/media/<pid>/<path:name>")
def media(pid, name):
    load(pid)
    as_dl = bool(request.args.get("dl"))
    return send_from_directory(pdir(pid), name, conditional=True, as_attachment=as_dl)


def selftest():
    """Vérifie que tout fonctionne (utilisé par GitHub après chaque fabrication de l'app).
    Chaque étape est testée même si une précédente échoue, pour tout voir en une fois."""
    import tempfile
    from pipeline import reframe
    from pipeline.utils import run
    failures = []

    def step(name, fn):
        try:
            info = fn()
            print(f"✅ {name}" + (f" — {info}" if info else ""), flush=True)
        except Exception as exc:
            traceback.print_exc()
            print(f"❌ {name} — {exc}", flush=True)
            failures.append(name)

    tmp = Path(tempfile.mkdtemp())
    src = tmp / "src.mp4"

    def t_ffmpeg():
        check_ffmpeg()
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=6", "-f", "lavfi",
             "-i", "sine=f=440:d=6", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)], "test")
        return shutil.which("ffmpeg")

    def t_opencv():
        import cv2
        cv2_, det = reframe._face_detector()
        assert det is not None, "modèle de visage introuvable"
        return f"OpenCV {cv2.__version__}"

    def t_ytdlp():
        import yt_dlp
        from yt_dlp.utils import download_range_func
        download_range_func(None, [(10, 20)])
        return yt_dlp.version.__version__

    def t_whisper():
        tr = transcribe(src, tmp, "tiny", "fr")
        return f"{len(tr['segments'])} segment(s)"

    def t_render(style, mode):
        def fn():
            words = [{"start": 1 + i * 0.4, "end": 1.35 + i * 0.4, "word": w}
                     for i, w in enumerate("Ceci est un test de sous-titres animés".split())]
            tr = {"segments": [{"start": 1, "end": 4, "text": "", "words": words}]}
            out = tmp / f"{style}.mp4"
            render_clip(src, tr, {"start": 0.5, "end": 5, "hook": "Test"}, out,
                        {"style": style, "reframe": mode}, tmp)
            assert out.exists() and out.stat().st_size > 10000, "fichier vide"
            return f"{out.stat().st_size // 1024} Ko"
        return fn

    step("FFmpeg", t_ffmpeg)
    step("Détection de visage", t_opencv)
    step("yt-dlp", t_ytdlp)
    step("Whisper", t_whisper)
    step("Rendu karaoké + suivi visage", t_render("karaoke", "face"))
    step("Rendu Hormozi + fond flou", t_render("hormozi", "blur"))
    shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        print("SELFTEST ÉCHEC :", ", ".join(failures))
        sys.exit(1)
    print("SELFTEST OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    try:
        check_ffmpeg()
    except PipelineError as e:
        print("\n⚠️ ", e, "\n")
    if ONLINE and not APP_PASSWORD:
        sys.exit("⛔ En ligne, définis la variable APP_PASSWORD (mot de passe du site) avant de lancer l'app.")
    url = f"http://127.0.0.1:{PORT}"
    if not ONLINE:  # déjà lancée ? on rouvre simplement la page
        with socket.socket() as _s:
            if _s.connect_ex(("127.0.0.1", PORT)) == 0:
                webbrowser.open(url)
                sys.exit(0)
    print(f"\n🎬 ShortMaker est lancé sur le port {PORT}\n   (Ctrl+C pour arrêter)\n")
    if not ONLINE and not os.environ.get("NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
