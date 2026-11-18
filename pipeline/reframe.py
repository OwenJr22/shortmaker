"""Recadrage vertical 9:16 qui suit le visage de la personne qui parle."""
import os
import sys
from pathlib import Path

import numpy as np

SAMPLE_EVERY = 0.4      # secondes entre deux analyses d'image
DEAD_ZONE = 0.07        # la caméra ne bouge que si le visage s'écarte de plus de 7 % de la largeur
MAX_KEYFRAMES = 90


CASCADE = "haarcascade_frontalface_default.xml"


def _cascade_path(cv2):
    """Cherche le modèle de visage : d'abord celui fourni avec l'app, sinon celui d'OpenCV."""
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    candidates = [here / "models" / CASCADE]
    hc = getattr(getattr(cv2, "data", None), "haarcascades", None)
    if hc:
        candidates.append(Path(hc) / CASCADE)
    return next((str(p) for p in candidates if p.exists()), None)


def _face_detector():
    try:
        import cv2
    except ImportError:
        return None, None
    path = _cascade_path(cv2)
    if not path:
        return cv2, None
    det = cv2.CascadeClassifier(path)
    return cv2, (None if det.empty() else det)


def crop_width(src_w, src_h):
    cw = int(round(src_h * 9 / 16))
    cw -= cw % 2
    return min(cw, src_w - (src_w % 2))


def track_faces(video_path, start, end, src_w, src_h):
    """Renvoie une liste [(t, x_gauche)] relative au début du clip, ou None si pas de visage."""
    cv2, det = _face_detector()
    if det is None:
        return None
    cw = crop_width(src_w, src_h)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    times, centers = [], []
    t = start
    scale = 480 / src_w if src_w > 480 else 1.0
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, None, fx=scale, fy=scale) if scale != 1 else frame
        gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        faces = det.detectMultiScale(gray, 1.1, 5, minSize=(int(30 * scale) or 20,) * 2)
        times.append(t - start)
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            centers.append((x + w / 2) / scale)
        else:
            centers.append(np.nan)
        t += SAMPLE_EVERY
    cap.release()

    arr = np.array(centers, dtype=float)
    if len(arr) == 0 or np.all(np.isnan(arr)):
        return None
    # Remplit les trous (images sans visage) par interpolation
    idx = np.arange(len(arr))
    good = ~np.isnan(arr)
    arr = np.interp(idx, idx[good], arr[good])
    # Filtre médian pour ignorer les fausses détections isolées
    k = 5
    padded = np.pad(arr, k // 2, mode="edge")
    arr = np.array([np.median(padded[i:i + k]) for i in range(len(arr))])

    # Stabilisation : on garde le cadre tant que le visage reste dans la zone morte
    keys, current = [], arr[0]
    for ti, c in zip(times, arr):
        if abs(c - current) > DEAD_ZONE * src_w:
            current = c
        keys.append((ti, current))

    def to_x(center):
        return float(np.clip(center - cw / 2, 0, src_w - cw))

    # Ne garde que les changements, avec une transition douce de 0,4 s
    out = [(0.0, to_x(keys[0][1]))]
    for (t0, c0), (t1, c1) in zip(keys, keys[1:]):
        if c1 != c0:
            out.append((t1, to_x(c0)))
            out.append((t1 + 0.4, to_x(c1)))
    if len(out) > MAX_KEYFRAMES:  # sécurité : vidéo très agitée -> cadre fixe moyen
        return [(0.0, to_x(float(np.median(arr))))]
    return out


def x_expression(keys):
    """Construit l'expression ffmpeg (interpolation linéaire entre les points clés)."""
    if len(keys) == 1:
        return f"{keys[0][1]:.1f}"
    expr = f"{keys[-1][1]:.1f}"
    for (t0, x0), (t1, x1) in reversed(list(zip(keys, keys[1:]))):
        if t1 - t0 <= 1e-6:
            continue
        seg = f"{x0:.1f}+({x1 - x0:.1f})*(t-{t0:.3f})/{t1 - t0:.3f}"
        expr = f"if(lt(t,{t1:.3f}),{seg},{expr})"
    return expr
