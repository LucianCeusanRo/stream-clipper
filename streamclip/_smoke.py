"""Bug-catching smoke test: the FULL pipeline on a synthetic sample + every web route. Fails on any traceback.

Run: python -m streamclip smoke [--real-whisper]
- Sample: 100 s of ffmpeg test pattern + tone/noise with two loud "reaction" bursts (generated, no footage).
- Data folder in a temp path WITH spaces and non-ASCII letters (catches Windows path bugs).
- Pipeline: "New clips from a link" with the local file -> chunking, transcription (fake words by default, or
  the real faster-whisper "tiny" model with --real-whisper), detection, layout, effects, real ffmpeg render.
- Checks: clips exist, are 1080x1920 at 30/60 fps, 10-60 s, have audio + a thumbnail; every GET route answers,
  safe POST routes work, no HTTP 500, no "Traceback" in the log, no exception in any thread.
"""
from pathlib import Path
import json, os, subprocess, sys, threading, time, urllib.error, urllib.request

assert os.environ.get("CLIPPER_HOME"), "run through `python -m streamclip smoke`"
from streamclip import util, db, jobs, pipeline, web, app, channels   # noqa: E402

FAIL = []
THREAD_ERRORS = []
_orig_hook = threading.excepthook


def _hook(a):
    THREAD_ERRORS.append(f"{a.thread.name if a.thread else '?'}: {a.exc_type.__name__}: {a.exc_value}")
    _orig_hook(a)


threading.excepthook = _hook
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def check(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what, flush=True)
    if not ok:
        FAIL.append(what)


def make_sample(path, secs=100):
    a = ("0.03*(random(0)*2-1)+0.25*sin(2*PI*220*t)*between(mod(t\\,4)\\,0\\,2)"
         "+0.7*sin(2*PI*1800*t)*(between(t\\,30\\,34)+between(t\\,70\\,74))*(0.5+0.5*sin(2*PI*5*t))")
    subprocess.run([util.tool("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r=30:d={secs}",
                    "-f", "lavfi", "-i", f"aevalsrc={a}:s=44100:d={secs}", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True, creationflags=NOWIN)


def fake_transcribe(wav, *a, **k):
    """Words that sound like a streamer reacting during the loud parts (fast, deterministic, no model download)."""
    from streamclip.transcribe import load_wav
    dur = len(load_wav(wav)) / 16000
    calm = "okay so we go in here and check this side then rotate".split()
    hype = "no way bro what was that let's go that's insane".split()
    words, t, i = [], 0.4, 0
    while t < dur - 1:
        loud = any(lo <= t % 60 < lo + 5 for lo in (9, 29, 49))
        w = (hype if loud else calm)[i % len(hype if loud else calm)]
        words.append({"w": w, "s": round(t, 2), "e": round(t + 0.3, 2), "p": 0.95}); t += 0.42; i += 1
    sents = [{"s": words[j]["s"], "e": words[min(j + 7, len(words) - 1)]["e"],
              "t": " ".join(x["w"] for x in words[j:j + 8]) + "."} for j in range(0, len(words), 8)]
    return words, sents


def probe(f):
    r = subprocess.run([util.tool("ffprobe"), "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:format=duration",
                        "-of", "json", str(f)], capture_output=True, text=True, creationflags=NOWIN)
    return json.loads(r.stdout or "{}")


def http(port, path, body=None):
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json", "X-Clipper-Token": web.TOKEN})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            resp.read()
            return resp.status
    except urllib.error.HTTPError as e:
        e.read()
        return e.code


def main(real_whisper=False):
    t0 = time.time()
    util.setup_logging()
    util.save_settings({"use_llm": False, "language": "en", "onboarded": True, "whisper_model": "tiny", "memory_mode": "low",
                        "chunk_minutes": 1})
    print(f"data folder: {util.DATA}")
    sample = util.DATA / "sample clip ăș.mp4"
    make_sample(sample)
    check(sample.exists(), "synthetic sample generated with ffmpeg")
    if not real_whisper:
        pipeline.transcribe = fake_transcribe

    print("pipeline:")
    j = jobs.submit(str(sample), clips=3)
    end = time.time() + 900
    while j["status"] not in ("gata", "eroare") and time.time() < end:
        time.sleep(1)
    check(j["status"] == "gata", f"job finished ({j['status']}: {j.get('error') or j.get('stage')})")
    clips = db.q("SELECT * FROM clips WHERE status!='deleted'")
    if real_whisper and not clips:            # the generated sample has tones, not speech: Whisper ran, found no words
        print("  skip clip checks (real Whisper + synthetic sample without speech: 0 words is the right answer)")
    else:
        check(len(clips) >= 1, f"{len(clips)} clip(s) made")
    for c in clips:
        p = probe(c["file"])
        v = next((s for s in p.get("streams", []) if s.get("codec_type") == "video"), {})
        a = any(s.get("codec_type") == "audio" for s in p.get("streams", []))
        fr = v.get("r_frame_rate", "0/1").split("/")
        fps = float(fr[0]) / float(fr[1] or 1)
        dur = float(p.get("format", {}).get("duration") or 0)
        check((v.get("width"), v.get("height")) == (1080, 1920) and round(fps) in (30, 60) and 10 <= dur <= 60 and a,
              f"clip #{c['id']}: {v.get('width')}x{v.get('height')} {fps:.0f} fps {dur:.1f} s audio={a}")
        thumb = c["thumb"] if "thumb" in c.keys() else None
        check(bool(thumb) and os.path.exists(thumb) and os.path.exists(str(c["file"])[:-4] + ".cover.jpg"),
              f"clip #{c['id']} has a cover (auto: payoff moment) + gallery thumbnail")
        check("GTA" not in (c["caption"] or "") + (c["hook"] or ""), f"clip #{c['id']} caption has no made-up game")

    if clips:
        print("stream card (mocked Kick stats):")
        from . import streamcard
        db.x("UPDATE videos SET channel=? WHERE id=?", ("kick:smoketest", clips[0]["video_id"]))
        streamcard._cache[("kick", "smoketest")] = (time.time(), {"live": True, "viewers": 1234, "followers": 56789, "game": "The Finals"})
        vid, cap = streamcard.apply(db.q("SELECT * FROM clips WHERE id=?", (clips[0]["id"],), one=True), "Nice one #gaming")
        p = probe(str(vid))
        v = next((s for s in p.get("streams", []) if s.get("codec_type") == "video"), {})
        check(str(vid).endswith(".card.mp4") and (v.get("width"), v.get("height")) == (1080, 1920)
              and any(s.get("codec_type") == "audio" for s in p.get("streams", [])), f"card overlay -> {Path(vid).name} 1080x1920 + audio")
        check(cap.startswith("Nice one 🔴") and cap.endswith("https://kick.com/smoketest #gaming"), f"channel link before hashtags: {cap}")

    print("channels + rotation (mocked):")
    channels.add("kick.com/smoketest")
    started = []

    class Rec:
        def __init__(self):
            self.stop, self.ended = threading.Event(), threading.Event()
    channels.poll_once(time.time(), lambda p, n: {"live": True, "title": "t", "game": "The Finals", "started": time.time(), "stream_id": "1"},
                       lambda c, s, vid: started.append(vid) or Rec())
    check(started == ["kick-smoketest-1"], "a live channel starts a recording")
    check(isinstance(app.plan_schedule()["items"], list), "planned schedule computes")

    print("web routes:")
    port = 19000 + os.getpid() % 500
    srv = web.serve(port)
    cid = clips[0]["id"] if clips else None
    gets = ["/", "/index.html", "/static/icon.png", "/api/state", "/api/styles", "/api/progress", "/api/version",
            "/api/clips", "/api/clips?status=queue&sort=plan", "/api/clips?status=posted", "/api/clips?status=all&sort=new",
            "/api/settings", "/api/jobs", "/api/log?n=50", "/api/tiktok",
            "/api/accounts", "/api/schedule", "/api/channels", "/api/system", "/api/multistream"]
    gets += [f"/media/{cid}/thumb", f"/media/{cid}/video"] if cid else []
    for g in gets:
        code = http(port, g)
        check(code == 200, f"GET {g} -> {code}")
    check(http(port, "/api/nope") == 404, "unknown route -> 404")
    posts = [("/api/settings", {"hashtags": "#gaming #clips", "rotate": True, "memory_mode": "low"}, 200),
             ("/api/settings", {"daily_post_cap": "lots"}, 400),
             ("/api/control", {"action": "clear_errors"}, 200), ("/api/control", {"action": "bogus"}, 400),
             ("/api/clip", {"id": 99999999, "action": "post"}, 404),
             ("/api/channels", {"action": "add", "channel": "twitch.tv/smoke_two"}, 200),
             ("/api/channels", {"action": "add", "channel": "not a channel"}, 400),
             ("/api/channels", {"action": "remove", "key": "twitch:smoke_two"}, 200),
             ("/api/accounts", {"action": "save", "account": {"name": "Smoke FB", "platform": "facebook"}}, 200),
             ("/api/multistream", {"action": "save", "dests": {"youtube": {"server": "rtmp://evil.example.com/x", "enabled": True}}}, 400),
             ("/api/multistream", {"action": "start"}, 400),           # nothing enabled / no keys -> clear error, no crash
             ("/api/multistream", {"action": "stop"}, 200),
             ("/api/job", {"source": "", "clips": 1}, 400)]
    if cid:
        posts += [("/api/clip", {"id": cid, "action": "set_game", "game": "The Finals"}, 200),
                  ("/api/clip", {"id": cid, "action": "set_cover", "t": 4.2}, 200),
                  ("/api/clip", {"id": cid, "action": "post"}, 200)]
    for path, body, want in posts:
        code = http(port, path, body)
        check(code == want, f"POST {path} {json.dumps(body, ensure_ascii=False)[:60]} -> {code} (want {want})")
    check(http(port, "/api/schedule") == 200, "schedule after queueing a clip")
    srv.shutdown(); srv.server_close()

    log_text = (util.DATA / "streamclip.log").read_text(encoding="utf-8", errors="replace")
    tb = [ln for ln in log_text.splitlines() if "Traceback" in ln]
    check(not tb, "no Traceback in the log" + ("" if not tb else f" ({len(tb)} found)"))
    if tb:
        i = log_text.find("Traceback"); print(log_text[max(0, i - 300): i + 2500])
    check(not THREAD_ERRORS, "no exception in background threads " + "; ".join(THREAD_ERRORS)[:300])
    print(f"\n{'SMOKE TEST PASSED ✔' if not FAIL else f'SMOKE TEST FAILED ✘ ({len(FAIL)})'} in {time.time() - t0:.0f} s")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main("--real-whisper" in sys.argv))
