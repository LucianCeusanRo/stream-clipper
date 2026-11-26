"""Auto-watch Kick / Twitch channels: poll each one, record when it goes live, stop when it ends.

Channels live in data/channels.json ({platform, name, enabled}); the live state (offline / live / recording /
error) is kept in memory and shown under Channels. Recording reuses the live recorder's chunking, so the normal
worker turns the chunks into clips (with the stream's real game for titles/hashtags).
Quiet by design: an offline channel is just checked again later (no log spam); errors and rate limits back off
exponentially (1, 2, 4 … 30 min) and are logged once, not on every poll. No windows, no dialogs.
"""
import subprocess, threading, time
from pathlib import Path
from . import db, game, platforms, recorder
from .util import DATA, cfg, load_json, log, save_json, spawn, forget, tool

FILE = DATA / "channels.json"
STATE = {}                 # key -> {status, title, game, since, last_check, next_check, fails, msg, vid}
ACTIVE = {}                # key -> ChannelRecorder
_lock = threading.RLock()
MAX_BACKOFF = 30 * 60


def key(platform, name):
    return f"{platform}:{name}"


def load():
    d = load_json(FILE, []) if FILE.exists() else []
    out = []
    for c in d if isinstance(d, list) else []:
        if isinstance(c, dict) and c.get("platform") in ("kick", "twitch") and platforms.NAME_RX.match(str(c.get("name", ""))):
            out.append({"platform": c["platform"], "name": c["name"].lower(), "enabled": c.get("enabled", True) is not False})
    return out


def save(chs):
    save_json(FILE, chs)


def add(text):
    plat, name = platforms.parse_channel(text)
    with _lock:
        chs = load()
        if any(c["platform"] == plat and c["name"] == name for c in chs):
            raise ValueError(f"{name} ({plat}) is already in the list")
        if len(chs) >= 25:
            raise ValueError("at most 25 channels")
        chs.append({"platform": plat, "name": name, "enabled": True}); save(chs)
    STATE.pop(key(plat, name), None)
    return {"platform": plat, "name": name, "enabled": True}


def remove(k):
    with _lock:
        save([c for c in load() if key(c["platform"], c["name"]) != k])
    stop(k); STATE.pop(k, None)


def set_enabled(k, on):
    with _lock:
        chs = load()
        for c in chs:
            if key(c["platform"], c["name"]) == k:
                c["enabled"] = bool(on)
        save(chs)
    if not on:
        stop(k)
    st = STATE.setdefault(k, {}); st["next_check"] = 0


def stop(k):
    rec = ACTIVE.pop(k, None)
    if rec:
        rec.stop.set()


def listing():
    out = []
    for c in load():
        k = key(c["platform"], c["name"])
        st = dict(STATE.get(k) or {})
        st.setdefault("status", "checking" if c["enabled"] else "off")
        if not c["enabled"]:
            st["status"] = "off"
        out.append(dict(c, key=k, **{x: st.get(x) for x in ("status", "title", "game", "since", "last_check", "msg", "vid")},
                        url=(f"https://kick.com/{c['name']}" if c["platform"] == "kick" else f"https://www.twitch.tv/{c['name']}")))
    return out


def poll_once(now=None, status_fn=None, start_fn=None):
    """One pass over the due channels. status_fn/start_fn are injectable for tests."""
    now = now or time.time()
    status_fn = status_fn or platforms.channel_status
    start_fn = start_fn or start_recording
    every = max(30, int(cfg().get("channel_check_every_sec", 90)))
    chs = load()
    keys = {key(c["platform"], c["name"]) for c in chs if c["enabled"]}
    for k in list(ACTIVE):                       # removed / disabled while recording
        if k not in keys:
            stop(k)
    for c in chs:
        k = key(c["platform"], c["name"])
        if not c["enabled"]:
            continue
        st = STATE.setdefault(k, {"status": "checking", "fails": 0, "next_check": 0})
        rec = ACTIVE.get(k)
        if rec and rec.ended.is_set():
            ACTIVE.pop(k, None); rec = None
            st["status"] = "offline"; st["msg"] = "live ended: clips are being made"
            log.info("channel %s: live ended", k)
        if now < st.get("next_check", 0):
            continue
        st["last_check"] = now
        try:
            s = status_fn(c["platform"], c["name"])
        except platforms.PlatformError as e:
            st["fails"] = st.get("fails", 0) + 1
            wait = min(MAX_BACKOFF, max(e.retry_after or 0, 60 * 2 ** (st["fails"] - 1)))
            st.update(next_check=now + wait, msg=f"{e} (next try in {wait // 60:.0f} min)")
            if not rec:
                st["status"] = "error"
            if st["fails"] == 1 or st["fails"] % 10 == 0:
                log.warning("channel %s: %s", k, e)
            continue
        if st.get("fails"):
            log.info("channel %s: reachable again", k)
        st.update(fails=0, next_check=now + every, title=s.get("title"), game=s.get("game"))
        if s.get("live"):
            st["since"] = s.get("started") or st.get("since") or now
            if not rec:
                vid = f"{c['platform']}-{c['name']}-{s.get('stream_id') or int(st['since'])}"
                st.update(status="recording", vid=vid, msg="")
                log.info("channel %s is LIVE (%s): recording", k, s.get("game") or "?")
                ACTIVE[k] = start_fn(c, s, vid)
            else:
                st["status"] = "recording"
        else:
            if rec:                              # the recorder notices the end itself; give it a nudge
                rec.stop.set()
            st.update(status="offline", since=None, msg=st.get("msg") if st.get("status") == "offline" else "")
    return listing()


def start_recording(c, s, vid):
    db.upsert_video(vid, (s.get("title") or c["name"])[:120], f"{c['platform']}:{c['name']}", s.get("started") or time.time(), "live")
    if s.get("game"):
        game.remember(vid, game.normalize(s["game"]), c["platform"])
    folder = DATA / vid
    rec = ChannelRecorder(c["platform"], c["name"], vid, s.get("started") or time.time(), folder, threading.Event())
    rec.start()
    return rec


class ChannelRecorder(recorder.LiveRecorder):
    """LiveRecorder for Kick/Twitch: media URL + headers from platforms.live_media."""
    def __init__(self, platform, name, vid, start_ts, folder: Path, stop):
        threading.Thread.__init__(self, daemon=True, name=f"rec-{name}")
        self.platform, self.name, self.vid, self.start_ts = platform, name, vid, start_ts
        self.folder, self.stop, self.ended = folder, stop, threading.Event()
        (folder / "live").mkdir(parents=True, exist_ok=True)

    def run(self):
        seg = int(cfg().get("chunk_minutes", 5) * 60)
        fails = 0
        try:
            while not self.stop.is_set():
                try:
                    url, hdrs = platforms.live_media(self.platform, self.name, cfg().get("video_max_height", 1080))
                    if self.platform == "kick":
                        url = platforms.hls_variant(url, cfg().get("video_max_height", 1080), hdrs)
                except platforms.PlatformError as e:
                    if "not live" in str(e):
                        break
                    url = None
                    log.warning("channel %s:%s: %s", self.platform, self.name, e)
                if url:
                    t = time.time()
                    self._record_h(url, hdrs, seg)
                    if time.time() - t > 120:
                        fails = 0
                self._register_finished(final=True)
                fails += 1
                if fails > 8:
                    break
                self.stop.wait(min(60, 5 * fails))
        except Exception:
            log.exception("channel recorder %s", self.vid)
        finally:
            self._register_finished(final=True)
            db.upsert_video(self.vid, None, None, None, "ended")
            self.ended.set()

    def _record_h(self, url, hdrs, seg):
        out = self.folder / "live" / "rec_%Y%m%d_%H%M%S.ts"
        net = ["-fflags", "+genpts+discardcorrupt", "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "10",
               "-rw_timeout", "30000000"]
        if hdrs:
            net += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in hdrs.items())]
        cmd = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", *net, "-i", url, "-map", "0:v:0", "-map", "0:a:0?",
               "-c", "copy", "-f", "segment", "-segment_time", str(seg), "-reset_timestamps", "1", "-strftime", "1", str(out)]
        p = spawn(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            while p.poll() is None and not self.stop.is_set():
                self.stop.wait(10)
                self._register_finished()
            if p.poll() is None:
                try:
                    p.stdin.write(b"q"); p.stdin.flush(); p.wait(15)
                except Exception:
                    p.kill()
        finally:
            forget(p)


def loop(stop_ev, watching_ev):
    """Background thread started by app.run_forever."""
    while not stop_ev.is_set():
        try:
            if watching_ev.is_set():
                poll_once()
            else:
                for k in list(ACTIVE):
                    stop(k)
        except Exception:
            log.exception("channel watcher")
        stop_ev.wait(5)
