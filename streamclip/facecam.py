"""Webcam/face finder used to pick the 9:16 layout.

Written for this project (not copied from another repo). Method, kept deliberately simple:
  1. grab a few frames spread over the clip with ffmpeg,
  2. run OpenCV's YuNet face detector on each frame (model: opencv_zoo, MIT, bundled in models/),
  3. a streamer webcam is a face that stays in roughly the same place in most frames;
     in-game characters move around, so they rarely pass this test.
The caller (layout.py) turns that face into a crop box, or falls back to the blur layout.
"""
import os, subprocess, urllib.request
from pathlib import Path

import numpy as np

YUNET = "face_detection_yunet_2023mar.onnx"
YUNET_SRC = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/" + YUNET
MODELS_DIR = Path(os.environ.get("CLIPPER_MODELS", Path(__file__).resolve().parent.parent / "models"))
ANALYSIS_W = 960          # frames are scaled to this width before detection
MIN_SCORE = 0.75          # YuNet confidence


def model_path():
    """Path of the bundled YuNet model; fetched from opencv_zoo once if someone deleted it."""
    target = MODELS_DIR / YUNET
    if target.is_file() and target.stat().st_size > 100_000:
        return str(target)
    os.makedirs(MODELS_DIR, exist_ok=True)
    with urllib.request.urlopen(YUNET_SRC, timeout=60) as resp:
        data = resp.read()
    partial = target.with_name(target.name + ".download")
    partial.write_bytes(data)
    os.replace(partial, target)
    return str(target)


def _ffmpeg():
    from .util import tool
    return tool("ffmpeg")


def sample_frames(video, start, end, n=8):
    """n BGR frames (numpy arrays, ANALYSIS_W wide) evenly spread between start and end seconds."""
    start = float(start or 0); end = float(end if end is not None else start + 30)
    span = max(0.5, end - start)
    frames = []
    for i in range(n):
        t = start + span * (i + 0.5) / n
        cmd = [_ffmpeg(), "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
               "-vf", f"scale={ANALYSIS_W}:-2", "-f", "image2pipe", "-vcodec", "png", "-"]
        r = subprocess.run(cmd, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0 or not r.stdout:
            continue
        import cv2
        img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            frames.append(img)
    return frames


def detect_faces(frames):
    """For each frame: list of faces [x, y, w, h, score] in pixels."""
    import cv2
    if not frames:
        return []
    h, w = frames[0].shape[:2]
    det = cv2.FaceDetectorYN.create(model_path(), "", (w, h), MIN_SCORE, 0.3, 50)
    out = []
    for f in frames:
        if f.shape[:2] != (h, w):
            f = cv2.resize(f, (w, h))
        _, faces = det.detect(f)
        out.append([[float(v) for v in row[:4]] + [float(row[-1])] for row in (faces if faces is not None else [])])
    return out


def _center(b):
    return b[0] + b[2] / 2, b[1] + b[3] / 2


def stable_face(dets, n_frames):
    """The face that shows up at (almost) the same spot in the most frames.
    Returns (median box [x, y, w, h] in px, number of frames it was seen in) or (None, 0)."""
    faces = [f for fr in dets for f in fr]
    if not faces:
        return None, 0
    best, best_hits = None, 0
    for cand in faces:
        cx, cy = _center(cand)
        tol = max(cand[2], cand[3]) * 0.6           # allowed drift: ~half a face
        group = []
        for fr in dets:                             # at most one match per frame
            near = [f for f in fr if abs(_center(f)[0] - cx) <= tol and abs(_center(f)[1] - cy) <= tol]
            if near:
                group.append(max(near, key=lambda f: f[4]))
        if len(group) > best_hits:
            best_hits = len(group)
            best = [float(np.median([g[k] for g in group])) for k in range(4)]
    return best, best_hits


def iou(a, b):
    """Overlap of two [x, y, w, h] boxes: intersection / union, 0..1."""
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0.0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    total = a[2] * a[3] + b[2] * b[3] - inter
    return inter / total if total > 0 else 0.0


def union(boxes):
    """Smallest [x, y, w, h] that contains every box."""
    x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes); y1 = max(b[1] + b[3] for b in boxes)
    return [x0, y0, x1 - x0, y1 - y0]


def stable_faces(dets, n_frames, min_hits=None):
    """Every face that stays in place over the sampled frames (e.g. two people on one webcam).
    -> [(median [x, y, w, h], frames seen), ...], most often seen first."""
    need = min_hits or max(3, n_frames // 2)
    found = []
    pool = [list(f) for fr in dets for f in fr]
    while pool:
        seed = max(pool, key=lambda f: f[4])
        cx, cy = _center(seed)
        tol = max(seed[2], seed[3]) * 0.6
        group = []
        for fr in dets:
            near = [f for f in fr if abs(_center(f)[0] - cx) <= tol and abs(_center(f)[1] - cy) <= tol]
            if near:
                group.append(max(near, key=lambda f: f[4]))
        pool = [f for f in pool if not (abs(_center(f)[0] - cx) <= tol and abs(_center(f)[1] - cy) <= tol)]
        if len(group) >= need:
            found.append(([float(np.median([g[k] for g in group])) for k in range(4)], len(group)))
    return sorted(found, key=lambda t: -t[1])


def group_faces(main, others, max_dx=9.0, max_dy=1.5):
    """The main face plus the other stable faces sitting next to it (same webcam: about the same height,
    within max_dx face-widths sideways and max_dy face-heights up/down). Boxes in the same units as main."""
    group = [main]
    for o in others:
        if iou(o, main) > 0.3:
            continue                                # that's the main face itself
        dx = abs(_center(o)[0] - _center(main)[0]) / max(main[2], 1e-6)
        dy = abs(_center(o)[1] - _center(main)[1]) / max(main[3], 1e-6)
        size = o[2] / max(main[2], 1e-6)
        if dx <= max_dx and dy <= max_dy and 0.5 <= size <= 2.0:
            group.append(o)
    return group


def face_box(face, frame_w, frame_h, widths=4.0):
    """A 16:9 box (fractions of the frame) around a face, about `widths` face-widths wide, face slightly above centre."""
    fx, fy, fw, fh = face[0] / frame_w, face[1] / frame_h, face[2] / frame_w, face[3] / frame_h
    bw = min(0.5, max(fw * widths, 0.12))
    bh = min(1.0, bw * (frame_w / frame_h) * 9 / 16)
    cx, cy = fx + fw / 2, fy + fh / 2
    x0 = float(np.clip(cx - bw / 2, 0, 1 - bw)); y0 = float(np.clip(cy - bh * 0.45, 0, 1 - bh))
    return [round(x0, 4), round(y0, 4), round(bw, 4), round(bh, 4)]


def find_cam(video, start=None, end=None, n=8):
    """{"mode": "face", "box": [x, y, w, h] fractions, "hits": k} or {"mode": "none"}."""
    frames = sample_frames(video, start, end, n)
    if len(frames) < 3:
        return {"mode": "none", "reason": "prea putine cadre"}
    h, w = frames[0].shape[:2]
    face, hits = stable_face(detect_faces(frames), len(frames))
    if face is None or hits < max(3, len(frames) // 2):
        return {"mode": "none", "reason": "nicio fata stabila"}
    return {"mode": "face", "box": face_box(face, w, h), "hits": hits}
