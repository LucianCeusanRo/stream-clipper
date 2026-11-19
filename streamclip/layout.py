"""Pick the 9:16 layout for a clip by looking at the actual frames.

1. YuNet face detection on frames sampled from the clip (model bundled in models/).
2. A face that stays put = streamer webcam. If it is inside the configured cam_box -> split with cam_box
   (exact crop of the streamer's cam overlay). Otherwise -> split with a 16:9 box around that face.
3. No stable face (cam off / full-screen game / BRB) -> 'blur': whole 16:9 frame over a blurred fill.
"""
from . import facecam
from .util import cfg, log


def decide(video, s0, e0):
    c = cfg()
    want = c.get("layout", "split")
    if want != "split" or not c.get("auto_cam", True):
        return want, c.get("cam_box")
    try:
        frames = facecam.sample_frames(video, s0, e0, 8)
        if len(frames) < 4:
            return "blur", None
        h, w = frames[0].shape[:2]
        dets = facecam.detect_faces(frames)
        face, hits = facecam.stable_face(dets, len(frames))
    except Exception as e:
        log.warning("detectie fata esuata (%s) -> folosesc cam_box din config", str(e)[:100])
        return "split", c.get("cam_box")
    if face is None or hits < 4:
        return "blur", None
    fx, fy, fw, fh = face[0] / w, face[1] / h, face[2] / w, face[3] / h
    if fw > 0.25:                      # huge face = full-screen camera (IRL), not an overlay
        return "blur", None
    cx, cy = fx + fw / 2, fy + fh / 2
    bx, by, bw, bh = c.get("cam_box", [0, 0, 0, 0])
    if bx <= cx <= bx + bw and by <= cy <= by + bh:
        return "split", [bx, by, bw, bh]
    # the cam is somewhere else (other streamer / new layout): a 16:9 box around the face,
    # wide enough to also catch a guest sitting next to the streamer
    box = facecam.face_box(face, w, h, widths=6.0)
    log.info("camera in alt loc: box automat %s", box)
    return "split", box
