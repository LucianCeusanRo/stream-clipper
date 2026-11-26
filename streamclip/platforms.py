"""Kick and Twitch through their public endpoints (no login, no API keys): live status, VOD info, media URLs.

Used by the channel auto-watcher (channels.py) and by "New clips from a link" for Kick (yt-dlp's Kick VOD
extractor breaks whenever Kick changes its site; the public JSON API below is what kick.com itself uses).
Every function returns plain dicts and raises PlatformError with a short, friendly message.
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"      # Twitch's own public web client id (same one yt-dlp uses)
NAME_RX = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{1,39}$")


class PlatformError(Exception):
    """Friendly message; .retry_after (s) is set for rate limits."""
    def __init__(self, msg, retry_after=None):
        super().__init__(msg)
        self.retry_after = retry_after


def parse_channel(text):
    """'kick.com/gs-xx', 'https://www.twitch.tv/shroud', 'kick:gs-xx', 'twitch shroud' -> ('kick'|'twitch', name)."""
    t = str(text or "").strip()
    m = re.match(r"^(kick|twitch)[:\s/]+([\w-]+)$", t, re.I)
    if m:
        plat, name = m.group(1).lower(), m.group(2)
    else:
        u = urlparse(t if "://" in t else "https://" + t)
        host = (u.hostname or "").lower()
        path = [p for p in u.path.split("/") if p]
        if host.endswith("kick.com"):
            plat = "kick"
        elif host.endswith("twitch.tv"):
            plat = "twitch"
        else:
            raise PlatformError("paste a Kick or Twitch channel, e.g. kick.com/name or twitch.tv/name")
        if not path:
            raise PlatformError("the link has no channel name")
        name = path[0]
    if not NAME_RX.match(name) or name.lower() in ("videos", "directory", "categories", "search", "following"):
        raise PlatformError(f"“{name}” doesn't look like a channel name")
    return plat, name.lower()


def _get(url, timeout=10, **kw):
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=timeout, **kw)
    except requests.RequestException as e:
        raise PlatformError(f"no connection to {urlparse(url).hostname} ({type(e).__name__})") from None
    return _check(r)


def _check(r):
    if r.status_code == 429:
        raise PlatformError("rate limited, trying again later", retry_after=int(r.headers.get("Retry-After") or 300))
    if r.status_code == 404:
        raise PlatformError("not found (wrong name, or the video was deleted)")
    if r.status_code >= 400:
        raise PlatformError(f"the site answered {r.status_code}", retry_after=120 if r.status_code >= 500 else None)
    try:
        return r.json()
    except ValueError:
        raise PlatformError("the site sent an unexpected answer (maybe a bot check); trying again later",
                            retry_after=300) from None


def _ts(s):
    """'2026-11-26 03:50:05' (UTC) / ISO -> unix time, or None."""
    if not s:
        return None
    s = str(s).replace("T", " ").replace("Z", "").split(".")[0].split("+")[0]
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _cat(cats):
    return ((cats or [{}])[0] or {}).get("name") or ""


# ---------- Kick ----------
def kick_channel(name, timeout=10):
    """-> {live, title, game, started, stream_id, url (HLS, only when live), viewers}"""
    j = _get(f"https://kick.com/api/v2/channels/{name}", timeout)
    if not isinstance(j, dict) or "slug" not in j:
        raise PlatformError("not found (wrong name?)")
    ls = j.get("livestream") or {}
    live = bool(ls and ls.get("is_live"))
    return {"live": live, "title": ls.get("session_title") or "", "game": _cat(ls.get("categories")) if live else "",
            "started": _ts(ls.get("start_time")) if live else None, "stream_id": str(ls.get("id") or "") if live else "",
            "url": j.get("playback_url") if live else None, "viewers": ls.get("viewer_count") or 0,
            "headers": {"User-Agent": UA, "Referer": "https://kick.com/"}}


def kick_vod(uuid, timeout=10):
    """yt-dlp-like info dict for a Kick VOD: {id, title, duration, url, categories, uploader, http_headers}"""
    j = _get(f"https://kick.com/api/v1/video/{uuid}", timeout)
    ls = j.get("livestream") or {}
    if not j.get("source"):
        raise PlatformError("this Kick video has no playable source (private, deleted or still processing)")
    return {"id": uuid, "title": ls.get("session_title") or f"Kick video {uuid[:8]}", "duration": (ls.get("duration") or 0) / 1000,
            "url": j["source"], "categories": [c.get("name") for c in ls.get("categories") or [] if c.get("name")],
            "uploader": (ls.get("channel") or {}).get("slug") or "", "is_live": False, "extractor": "kick:api",
            "http_headers": {"User-Agent": UA, "Referer": "https://kick.com/"}, "timestamp": _ts(ls.get("start_time"))}


def kick_vod_from_list(slug, vid, timeout=15):
    items = _get(f"https://kick.com/api/v2/channels/{slug}/videos", timeout)
    for it in items if isinstance(items, list) else []:
        if vid in (str((it.get("video") or {}).get("uuid")), str(it.get("vod_id")), str(it.get("slug"))) and it.get("source"):
            return {"id": vid, "title": it.get("session_title") or f"Kick video {vid[:8]}", "duration": (it.get("duration") or 0) / 1000,
                    "url": it["source"], "categories": [c.get("name") for c in it.get("categories") or [] if c.get("name")],
                    "uploader": slug, "is_live": False, "extractor": "kick:api",
                    "http_headers": {"User-Agent": UA, "Referer": "https://kick.com/"}, "timestamp": _ts(it.get("start_time"))}
    raise PlatformError("not found (wrong link, or the video was deleted)")


def kick_info(url):
    """Info dict for a kick.com link (VOD or live channel), or None if the link isn't Kick."""
    u = urlparse(url)
    if not (u.hostname or "").lower().endswith("kick.com"):
        return None
    path = [p for p in u.path.split("/") if p]
    m = re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", path[-1] if path else "")
    if m and "videos" in path:
        try:
            return kick_vod(path[-1])
        except PlatformError as e:
            # Kick's newer video ids are not served by /api/v1/video (yt-dlp issue #17284): look the video up in
            # the channel's public video list instead, which carries the playable HLS source
            if "not found" not in str(e) or path[0] == "videos":
                raise
            return kick_vod_from_list(path[0].lower(), path[-1])
    if path and NAME_RX.match(path[0]) and len(path) == 1:
        ch = kick_channel(path[0].lower())
        if not ch["live"]:
            raise PlatformError(f"{path[0]} is not live right now: paste one of their videos (kick.com/{path[0]}/videos/…) "
                                "or add the channel under Channels to record the next live automatically")
        return {"id": f"kick-{path[0].lower()}-{ch['stream_id']}", "title": ch["title"], "is_live": True, "url": ch["url"],
                "categories": [ch["game"]] if ch["game"] else [], "uploader": path[0], "extractor": "kick:api",
                "http_headers": ch["headers"], "formats": []}
    return None


# ---------- Twitch ----------
def _gql(query, timeout=10):
    try:
        r = requests.post("https://gql.twitch.tv/gql", json={"query": query},
                          headers={"Client-ID": TWITCH_CLIENT_ID, "User-Agent": UA}, timeout=timeout)
    except requests.RequestException as e:
        raise PlatformError(f"no connection to Twitch ({type(e).__name__})") from None
    j = _check(r)
    if isinstance(j, dict) and j.get("errors"):
        raise PlatformError("Twitch refused the request; trying again later", retry_after=300)
    return (j or {}).get("data") or {}


def twitch_channel(name, timeout=10):
    d = _gql('query{user(login:"%s"){login stream{id title createdAt viewersCount game{displayName}}}}' % name, timeout)
    u = d.get("user")
    if u is None:
        raise PlatformError("not found (wrong name?)")
    s = u.get("stream") or {}
    live = bool(s)
    return {"live": live, "title": s.get("title") or "", "game": (s.get("game") or {}).get("displayName") or "",
            "started": _ts(s.get("createdAt")), "stream_id": str(s.get("id") or ""), "url": None,
            "viewers": s.get("viewersCount") or 0, "headers": {}}


def channel_status(platform, name, timeout=10):
    return kick_channel(name, timeout) if platform == "kick" else twitch_channel(name, timeout)


def live_media(platform, name, max_h=1080):
    """-> (HLS url, headers) of a live channel. Kick: from its API. Twitch: yt-dlp (it handles the access token)."""
    if platform == "kick":
        ch = kick_channel(name)
        if not ch["live"] or not ch["url"]:
            raise PlatformError("the channel is not live")
        return ch["url"], ch["headers"]
    from yt_dlp import YoutubeDL
    from .jobs import live_stream_url
    from .util import ytdlp_opts
    try:
        with YoutubeDL(dict(ytdlp_opts(), quiet=True, skip_download=True, noplaylist=True)) as y:
            info = y.extract_info(f"https://www.twitch.tv/{name}", download=False)
    except Exception as e:
        raise PlatformError("Twitch: " + ("the channel is not live" if "not currently live" in str(e) else str(e)[:120])) from None
    url, hdrs = live_stream_url(info, max_h)
    if not url:
        raise PlatformError("Twitch: no playable stream found")
    return url, hdrs


def hls_variant(url, max_h=1080, headers=None, timeout=10):
    """Master playlist -> URL of the best variant <= max_h (ffmpeg would otherwise take the first one listed)."""
    try:
        r = requests.get(url, headers=dict({"User-Agent": UA}, **(headers or {})), timeout=timeout)
        text = r.text if r.ok else ""
    except requests.RequestException:
        return url
    if "#EXT-X-STREAM-INF" not in text:
        return url
    best, lines = None, text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF") and i + 1 < len(lines):
            h = re.search(r"RESOLUTION=\d+x(\d+)", line)
            bw = re.search(r"BANDWIDTH=(\d+)", line)
            key = (int(h.group(1)) if h else 0, int(bw.group(1)) if bw else 0)
            if key[0] <= max_h and (best is None or key > best[0]):
                best = (key, lines[i + 1].strip())
    if not best:
        return url
    from urllib.parse import urljoin
    return urljoin(url, best[1])


def friendly(e):
    """yt-dlp / network exception -> one short sentence for the app (no 'ERROR: [kick:vod] id:' noise)."""
    s = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    s = re.sub(r"^(ERROR:\s*)?(\[[\w:]+\]\s*)?([\w-]+:\s*)?", "", s)
    low = s.lower()
    if "not_found" in low or "404" in low or "does not exist" in low:
        return "the video wasn't found (deleted, private, or a typo in the link)"
    if "private" in low or "subscriber" in low or "members-only" in low:
        return "this video is private or for subscribers only"
    if "403" in low or "forbidden" in low:
        return "the site blocked the download (403); try again later"
    if "timed out" in low or "connection" in low or "getaddrinfo" in low or "name resolution" in low:
        return "no internet connection to the site; check the connection and try again"
    if "unsupported url" in low:
        return "this site isn't supported: paste a YouTube, Kick, Twitch or TikTok link, or a video file"
    return s[:200]
