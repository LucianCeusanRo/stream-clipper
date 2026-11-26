"""Demo mode: builds a synthetic test "stream" with ffmpeg (no real footage, no copyrighted material), runs the real
moment detection + rendering on it, and opens the dashboard with the resulting clips.

Whisper is skipped: the transcript is a scripted list of words (English, or Romanian with DEMO_LANG=ro), so the demo runs in a few minutes on any CPU.
Used to make the screenshots in docs/. Usage:

    python tools/demo.py            # then open http://127.0.0.1:8833
    DEMO_AUTOSUBMIT=0 python tools/demo.py   # empty dashboard; paste the demo video path yourself (used for the demo GIF)
    DEMO_WIZARD=1 python tools/demo.py       # show the first-run wizard

With auto-submit on, it also adds example accounts (2 TikTok + 1 YouTube Shorts, none really logged in) and
fake queue/posted history so every page has something to show. Nothing is ever uploaded.
"""
import os, sys, tempfile, time, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.setdefault("CLIPPER_HOME", str(Path(tempfile.gettempdir()) / "stream-clipper-demo")))
os.environ.setdefault("CLIPPER_CONFIG", str(ROOT / "config.example.yaml"))
os.environ.setdefault("CLIPPER_FONTS", str(ROOT / "fonts"))
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from streamclip import accounts, db, jobs, pipeline, util, web  # noqa: E402

SECS = 240
PEAKS = [(38, "ras"), (96, "rage"), (158, "wow"), (205, "chat")]
LINES_EN = {
    "ras": "hahaha I can't breathe bro lmao hahaha".split(),
    "rage": "no way he hit me again what the hell".split(),
    "wow": "oh my god did you see that jump".split(),
    "chat": "chat says I'm the worst driver ever bro".split(),
}
FILLER_EN = "okay let's go over there and see what we do now this mission is long".split()
LINES_RO = {
    "ras": "hahaha nu pot frate hahaha am murit de râs".split(),
    "rage": "nu se poate bă iar m-a lovit mașina gata".split(),
    "wow": "doamne ce a fost asta ai văzut săritura".split(),
    "chat": "chatul zice că sunt cel mai prost șofer aoleu".split(),
}
FILLER_RO = "hai că mergem acolo și vedem ce facem acum uite misiunea asta e lungă".split()
LANG = os.environ.get("DEMO_LANG", "en")
LINES, FILLER = (LINES_RO, FILLER_RO) if LANG == "ro" else (LINES_EN, FILLER_EN)


def make_video(out):
    """Conway's Game of Life as 'gameplay', a labelled box as 'webcam', loud bursts in the audio at the PEAKS."""
    wav = out.with_suffix(".wav")
    sr = 16000; t = np.arange(SECS * sr) / sr
    x = 0.03 * np.random.RandomState(1).randn(len(t))
    for p, _ in PEAKS:
        m = (t >= p) & (t < p + 5)
        x[m] += 0.55 * np.sin(2 * np.pi * 1500 * t[m]) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 5 * t[m])))
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    font = (ROOT / "fonts" / "Montserrat-ExtraBold.ttf").as_posix().replace(":", "\\:")
    vf = (f"[0:v]scale=1920:1080:flags=neighbor,setsar=1[g];[1:v]scale=456:256[c];[g][c]overlay=0:128,"
          f"drawbox=x=0:y=128:w=456:h=256:color=white@0.9:t=4,"
          f"drawtext=fontfile='{font}':text='WEBCAM (demo)':x=40:y=240:fontsize=40:fontcolor=white,"
          f"drawtext=fontfile='{font}':text='synthetic demo made with ffmpeg':x=1330:y=1020:fontsize=34:fontcolor=white@0.8[v]")
    util.run(["ffmpeg", "-y", "-v", "error",
              "-f", "lavfi", "-i", "life=s=480x270:rate=30:ratio=0.12:mold=12:life_color=#00e5ff:death_color=#141420:mold_color=#2a1846",
              "-f", "lavfi", "-i", "gradients=s=456x256:rate=30:speed=0.02:c0=0x2b1055:c1=0xff2e55",
              "-i", wav, "-filter_complex", vf, "-map", "[v]", "-map", "2:a", "-t", str(SECS),
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-shortest", str(out)], timeout=1800)
    wav.unlink(missing_ok=True)


def fake_transcribe(_wav):
    """Scripted words: filler talk, and a short Romanian exclamation at each loud moment."""
    words, t, i = [], 1.0, 0
    peaks = {p: LINES[k] for p, k in PEAKS}
    while t < SECS - 1:
        hit = next((p for p in peaks if p <= t < p + 5), None)
        if hit is not None:
            for w in peaks[hit]:
                words.append({"w": w, "s": round(t, 2), "e": round(t + 0.32, 2), "p": 0.95}); t += 0.42
            t = max(t, hit + 5.2)
            continue
        words.append({"w": FILLER[i % len(FILLER)], "s": round(t, 2), "e": round(t + 0.3, 2), "p": 0.9})
        i += 1; t += 0.48
    sents = [{"s": g[0]["s"], "e": g[-1]["e"], "t": " ".join(w["w"] for w in g) + "."}
             for g in (words[k:k + 8] for k in range(0, len(words), 8))]
    return words, sents


def seed_accounts_and_history():
    """Example accounts + queue + posted rows (demo data only: URLs point to nothing real)."""
    accounts.save_all([
        {"id": "alex-clips", "name": "@alex.clips (demo)", "platform": "tiktok", "hashtags": ["#gaming", "#clips"]},
        {"id": "alex-funny", "name": "@alex.funny (demo)", "platform": "tiktok", "hashtags": ["#funny", "#fyp"],
         "daily_cap": 8, "interval_min": 45, "interval_max": 90},
        {"id": "alex-shorts", "name": "Alex Shorts (demo)", "platform": "youtube", "hashtags": ["#shorts", "#gaming"]},
    ])
    accounts.profile_dir(accounts.get("alex-clips")).mkdir(parents=True, exist_ok=True)   # shows as "logged in"
    t0 = time.time() + 180
    while time.time() < t0:
        rows = db.q("SELECT id FROM clips WHERE status='pending' ORDER BY viral DESC, id")
        busy = any(j["status"] not in ("gata", "eroare", "done", "error") for j in jobs.list_jobs())
        if len(rows) >= 4 and not busy:
            break
        time.sleep(2)
    rows = [r["id"] for r in db.q("SELECT id FROM clips WHERE status='pending' ORDER BY viral DESC, id")]
    if len(rows) < 3:
        return
    now = time.time()
    db.x("UPDATE clips SET status='posted', account='alex-clips', posted_at=?, url=? WHERE id=?",
         (now - 7200, "https://www.tiktok.com/@alex.clips/video/demo1", rows[0]))
    yt = db.clone_clip(rows[0], "alex-shorts")
    db.x("UPDATE clips SET status='posted', posted_at=?, url=? WHERE id=?",
         (now - 5400, "https://youtube.com/shorts/demo1", yt))
    db.x("UPDATE clips SET status='posted', account='alex-funny', posted_at=?, url=? WHERE id=?",
         (now - 2900, "https://www.tiktok.com/@alex.funny/video/demo2", rows[1]))
    db.x("UPDATE clips SET status='queued', queued_at=?, account='alex-clips' WHERE id=?", (now - 600, rows[2]))
    db.clone_clip(rows[2], "alex-shorts")
    print("demo accounts + history added", flush=True)


def main():
    util.setup_logging()
    util.save_settings({"language": LANG, "ui_language": LANG, "streamer_name": "Alex", "game": "Counter-Strike 2",
                        "credit_text": "@alex on YouTube (demo)" if LANG != "ro" else "@alex pe YouTube (demo)",
                        "hashtags": ["#clip"], "use_llm": False, "auto_cam": False, "layout": "split",
                        "cam_box": [0.0, 0.118, 0.238, 0.238],
                        "onboarded": os.environ.get("DEMO_WIZARD", "0") != "1"})
    pipeline.transcribe = fake_transcribe
    src = HOME / "demo_stream.mp4"
    if not src.exists():
        print("building the test video...", flush=True)
        make_video(src)
    port = int(os.environ.get("DEMO_PORT", "8833"))
    web.serve(port)
    if os.environ.get("DEMO_AUTOSUBMIT", "1") != "0" and not db.q("SELECT id FROM clips LIMIT 1"):
        jobs.submit(str(src), clips=4)
        seed_accounts_and_history()
    print(f"open http://127.0.0.1:{port}", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
