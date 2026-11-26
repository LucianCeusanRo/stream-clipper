"""Native Twitch clips of the detected highlights, through Twitch's official Helix API ("Create Clip From VOD",
open beta), only for YOUR channel or channels where you are an editor. Sign-in = Twitch device code (you type a
short code on twitch.tv/activate; no password ever goes through this app). Needs your own free Twitch app
(dev.twitch.tv → Applications → Client type: Public) for the Client ID. Tokens are stored encrypted (DPAPI)."""
import math
import re
import threading
import time

import requests

from . import secretstore
from .util import DATA, cfg, log

ID = "https://id.twitch.tv/oauth2"
HELIX = "https://api.twitch.tv/helix"
SCOPES = "channel:manage:clips editor:manage:clips clips:edit"
TOKEN = DATA / "twitch_token.json"
AUTH = {"state": "off", "user_code": None, "uri": None, "msg": ""}


class TwitchError(Exception):
    pass


def client_id():
    cid = str(cfg().get("twitch_client_id") or "").strip()
    if not re.fullmatch(r"[a-z0-9]{20,40}", cid):
        raise TwitchError("add your Twitch app's Client ID first (dev.twitch.tv → Applications → Register, Client type: Public)")
    return cid


def _req(method, url, **kw):
    try:
        r = requests.request(method, url, timeout=15, **kw)
    except requests.RequestException as e:
        raise TwitchError(f"no connection to Twitch ({type(e).__name__})") from None
    try:
        j = r.json()
    except ValueError:
        j = {}
    return r.status_code, j


# ---------- device-code sign-in ----------
def start_auth():
    cid = client_id()
    code, j = _req("POST", f"{ID}/device", data={"client_id": cid, "scopes": SCOPES})
    if code != 200 or "device_code" not in j:
        raise TwitchError(f"Twitch refused the sign-in: {j.get('message') or code}")
    AUTH.update(state="waiting", user_code=j["user_code"], uri=j.get("verification_uri") or "https://www.twitch.tv/activate",
                msg="type the code on twitch.tv/activate")
    threading.Thread(target=_poll, args=(cid, j["device_code"], int(j.get("interval", 5)), int(j.get("expires_in", 1800))),
                     daemon=True, name="twitch-auth").start()
    return dict(AUTH)


def _poll(cid, device_code, interval, expires):
    end = time.time() + expires
    while time.time() < end and AUTH["state"] == "waiting":
        time.sleep(max(2, interval))
        try:
            code, j = _req("POST", f"{ID}/token", data={"client_id": cid, "scopes": SCOPES, "device_code": device_code,
                                                         "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        except TwitchError:
            continue
        if code == 200 and j.get("access_token"):
            j["expires_at"] = time.time() + int(j.get("expires_in", 3600)) - 60
            who = _validate(j["access_token"])
            j.update(login=who.get("login"), user_id=who.get("user_id"))
            secretstore.save_json(TOKEN, j)
            AUTH.update(state="ok", user_code=None, msg=f"connected as {j['login']}")
            log.info("Twitch clips: connected as %s", j["login"])
            return
        if str(j.get("message", "")).lower() not in ("authorization_pending", "slow_down"):
            AUTH.update(state="error", user_code=None, msg=f"sign-in failed: {j.get('message') or code}")
            return
    if AUTH["state"] == "waiting":
        AUTH.update(state="error", user_code=None, msg="the code expired - press Connect again")


def _validate(tok):
    code, j = _req("GET", f"{ID}/validate", headers={"Authorization": f"OAuth {tok}"})
    if code != 200:
        raise TwitchError("Twitch sign-in is no longer valid - press Connect again")
    return j


def token():
    t = secretstore.load_json(TOKEN, None)
    if not t:
        raise TwitchError("connect your Twitch account first (Accounts → Twitch clips)")
    if t.get("expires_at", 0) > time.time():
        return t
    code, j = _req("POST", f"{ID}/token", data={"client_id": client_id(), "grant_type": "refresh_token",
                                                 "refresh_token": t.get("refresh_token", "")})
    if code != 200 or not j.get("access_token"):
        raise TwitchError("Twitch sign-in expired - press Connect again")
    t.update(access_token=j["access_token"], refresh_token=j.get("refresh_token", t.get("refresh_token")),
             expires_at=time.time() + int(j.get("expires_in", 3600)) - 60)
    secretstore.save_json(TOKEN, t)
    return t


def disconnect():
    TOKEN.unlink(missing_ok=True)
    AUTH.update(state="off", user_code=None, msg="")


def status():
    t = secretstore.load_json(TOKEN, None) or {}
    return {"connected": bool(t.get("access_token")), "login": t.get("login"), "auth": dict(AUTH),
            "client_id_set": bool(str(cfg().get("twitch_client_id") or "").strip()),
            "channels": allowed(t.get("login")), "auto": bool(cfg().get("twitch_clips_auto", False))}


def allowed(own=None):
    """Your channel + channels you listed as editor. Nothing else is ever clipped."""
    out = [own.lower()] if own else []
    for c in cfg().get("twitch_clip_channels") or []:
        c = str(c).strip().lower().lstrip("@")
        if re.fullmatch(r"[a-z0-9_]{3,25}", c) and c not in out:
            out.append(c)
    return out


# ---------- clip ----------
def _helix(method, path, t, **kw):
    code, j = _req(method, f"{HELIX}/{path}", headers={"Authorization": f"Bearer {t['access_token']}",
                                                     "Client-Id": client_id()}, **kw)
    if code == 401:
        raise TwitchError("Twitch says you are not allowed (not your channel, not an editor, or sign-in expired)")
    if code == 403:
        raise TwitchError("this channel only lets followers/subscribers clip, or clipping is off")
    if code >= 400:
        raise TwitchError(f"Twitch: {j.get('message') or code}")
    return j


def vod_for(clip, bid, t):
    """(vod_id, end offset in the VOD) for a clip from a Twitch live recording or a pasted Twitch VOD link."""
    from . import db
    vid = str(clip["video_id"] or "")
    m = re.fullmatch(r"twitch-[\w-]+-(\d+)", vid)
    if m:                                            # recorded live: the VOD that belongs to this stream
        for v in _helix("GET", "videos", t, params={"user_id": bid, "type": "archive", "first": 10}).get("data", []):
            if str(v.get("stream_id")) == m.group(1):
                return v["id"], clip["end"]
        raise TwitchError("no VOD for this stream (Twitch VODs must be turned on in your channel settings)")
    if vid.startswith("job-"):
        j = db.q("SELECT source FROM jobs WHERE id=?", (vid[4:],), one=True)
        m = re.search(r"twitch\.tv/videos/(\d+)", (j["source"] if j else "") or "")
        if m:
            return m.group(1), clip["end"]
    raise TwitchError("this clip doesn't come from a Twitch live or VOD")


def create(clip):
    """Create a native Twitch clip of this highlight. -> {id, edit_url}."""
    from . import streamcard
    src = streamcard.source(clip)
    if not src or src[0] != "twitch":
        raise TwitchError("not a Twitch clip")
    t = token()
    name = src[1]
    if name not in allowed(t.get("login")):
        raise TwitchError(f"{name} is not your channel - add it under 'Channels where I'm an editor' only if you are one")
    users = _helix("GET", "users", t, params={"login": name}).get("data") or []
    if not users:
        raise TwitchError(f"Twitch user {name} not found")
    bid = users[0]["id"]
    vod, end = vod_for(clip, bid, t)
    dur = round(min(60.0, max(5.0, float(clip["end"]) - float(clip["start"]))), 1)
    off = max(int(math.ceil(float(end))), int(math.ceil(dur)))
    title = re.sub(r"#\w+", "", str(clip["title"] or clip["hook"] or "Highlight")).strip()[:100] or "Highlight"
    j = _helix("POST", "videos/clips", t, params={"editor_id": t["user_id"], "broadcaster_id": bid, "vod_id": vod,
                                                   "vod_offset": off, "duration": dur, "title": title})
    d = (j.get("data") or [{}])[0]
    if not d.get("id"):
        raise TwitchError("Twitch did not return a clip id")
    log.info("Twitch clip created for %s: %s", name, d.get("edit_url"))
    return {"id": d["id"], "edit_url": d.get("edit_url") or f"https://clips.twitch.tv/{d['id']}"}
