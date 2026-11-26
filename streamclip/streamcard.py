"""Stream card on posted / exported clips: Kick or Twitch logo, channel name, 🔴 LIVE + 👀 viewers while the channel
is live, 👥 followers. Only real numbers straight from the platform (Kick public API, Twitch GQL): a number that
isn't available is left out, never guessed. The card sits top-left inside TikTok's safe area (below the top tabs,
left of the right-hand buttons, far from the caption zone) and appears after the hook box. The channel link goes
in the description; the burned-in captions stay the streamer's spoken words only."""
import re
import subprocess
import time
from pathlib import Path

from . import platforms
from .util import FONTS, ROOT, cfg, log, tool

W = 1080
X, Y = 56, 172                   # TikTok safe area: top tabs end ~150 px, right buttons start ~x=920
MAX_W = 860
_cache = {}
EMOJI = ROOT / "assets" / "emoji"


def source(clip):
    """(platform, channel) the clip comes from, or None (YouTube / local file / unknown)."""
    from . import db
    vid = str(clip["video_id"] or "")
    row = db.q("SELECT channel FROM videos WHERE id=?", (vid,), one=True)
    ch = str((row["channel"] if row else "") or "")
    m = re.fullmatch(r"(kick|twitch):([\w-]+)", ch)
    if m:
        return m.group(1), m.group(2).lower()
    m = re.fullmatch(r"(kick|twitch)-([\w-]+)-\d+", vid)     # recorded by Channels / pasted live channel
    if m:
        return m.group(1), m.group(2).lower()
    return None


def link(platform, name):
    return f"https://kick.com/{name}" if platform == "kick" else f"https://www.twitch.tv/{name}"


def _int(v):
    try:
        n = int(str(v).replace(",", "").strip())
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def stats(platform, name, timeout=8):
    """{live, viewers, followers, game}: numbers are None when the platform doesn't give them. Cached 3 min."""
    key = (platform, name)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 180:
        return hit[1]
    out = {"live": False, "viewers": None, "followers": None, "game": ""}
    try:
        if platform == "kick":
            j = platforms._get(f"https://kick.com/api/v2/channels/{name}", timeout)
            ls = (j or {}).get("livestream") or {}
            out["followers"] = _int(j.get("followers_count", j.get("followersCount")))
            out["live"] = bool(ls and ls.get("is_live"))
            if out["live"]:
                out["viewers"] = _int(ls.get("viewer_count"))
                out["game"] = platforms._cat(ls.get("categories"))
        else:
            d = platforms._gql('query{user(login:"%s"){followers{totalCount} stream{viewersCount game{displayName}}}}' % name, timeout)
            u = d.get("user") or {}
            out["followers"] = _int((u.get("followers") or {}).get("totalCount"))
            s = u.get("stream")
            out["live"] = bool(s)
            if s:
                out["viewers"] = _int(s.get("viewersCount"))
                out["game"] = (s.get("game") or {}).get("displayName") or ""
    except Exception as e:                       # offline API / rate limit: card shows only what is certain
        log.info("stream card: no stats for %s/%s (%s)", platform, name, platforms.friendly(e))
    _cache[key] = (time.time(), out)
    return out


def num(n):
    return f"{n:,}"                              # exact, with thousands separators (never rounded or estimated)


def _logo(platform, size):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = size / 12
    if platform == "kick":
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(2.2 * u), fill=(83, 252, 24, 255))
        k = (0, 0, 0, 255)                       # blocky "K"
        d.rectangle([3 * u, 2.5 * u, 5 * u, 9.5 * u], fill=k)
        d.polygon([(5 * u, 5.2 * u), (7.4 * u, 2.5 * u), (9.6 * u, 2.5 * u), (6.6 * u, 6 * u), (9.6 * u, 9.5 * u),
                   (7.4 * u, 9.5 * u), (5 * u, 6.8 * u)], fill=k)
    else:
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(2.2 * u), fill=(145, 70, 255, 255))
        wht, pur = (255, 255, 255, 255), (145, 70, 255, 255)
        d.polygon([(3 * u, 2.2 * u), (9.6 * u, 2.2 * u), (9.6 * u, 7 * u), (7.6 * u, 9 * u), (6 * u, 9 * u),
                   (4.8 * u, 10.2 * u), (4.8 * u, 9 * u), (3 * u, 9 * u)], fill=wht)
        d.rectangle([5.2 * u, 4 * u, 6 * u, 6.6 * u], fill=pur)
        d.rectangle([7.2 * u, 4 * u, 8 * u, 6.6 * u], fill=pur)
    return im


def _emoji(code, size):
    from PIL import Image
    p = EMOJI / f"{code}.png"
    return Image.open(p).convert("RGBA").resize((size, size), Image.LANCZOS) if p.exists() else None


def card_png(platform, name, st, out, show_viewers=True, show_followers=True):
    """Draw the card (transparent PNG). Items that don't fit are dropped from the end, never squeezed."""
    from PIL import Image, ImageDraw, ImageFont
    f1 = ImageFont.truetype(str(FONTS / "Montserrat-Black.ttf"), 40)
    f2 = ImageFont.truetype(str(FONTS / "Montserrat-ExtraBold.ttf"), 27)
    items = []                                   # (emoji code, text, colour)
    if st.get("live"):
        items.append(("1f534", "LIVE now", (255, 80, 80)))
        if show_viewers and st.get("viewers") is not None:
            items.append(("1f440", f"{num(st['viewers'])} watching", (255, 255, 255)))
    if show_followers and st.get("followers") is not None:
        items.append(("1f465", f"{num(st['followers'])} followers", (230, 230, 235)))
    if st.get("live") and st.get("game"):
        items.append(("1f3ae", st["game"][:28], (210, 210, 220)))
    pad, logo, gap, es = 18, 84, 16, 28
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tx = pad + logo + gap
    name_w = tmp.textlength(name, font=f1)
    row, line2 = [], 0
    for code, txt, col in items:
        w = es + 8 + tmp.textlength(txt, font=f2) + (22 if row else 0)
        if tx + line2 + w + pad > MAX_W:
            break
        row.append((code, txt, col)); line2 += w
    cw = int(min(MAX_W, max(tx + name_w, tx + line2) + pad + 6))
    ch = logo + 2 * pad
    im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, cw - 1, ch - 1], radius=26, fill=(14, 14, 18, 200))
    im.alpha_composite(_logo(platform, logo), (pad, pad))
    y1 = pad - 2 if row else pad + (logo - 44) // 2
    nm = name
    while tmp.textlength(nm, font=f1) > cw - tx - pad and len(nm) > 3:
        nm = nm[:-2] + "…"
    d.text((tx, y1), nm, font=f1, fill=(255, 255, 255))
    x, y2 = tx, pad + 50
    for i, (code, txt, col) in enumerate(row):
        if i:
            x += 22
        e = _emoji(code, es)
        if e:
            im.alpha_composite(e, (int(x), y2 + 2))
        x += es + 8
        d.text((x, y2), txt, font=f2, fill=col)
        x += tmp.textlength(txt, font=f2)
    im.save(out)
    return out


def caption_with_link(caption, platform, name):
    """'text #tags' -> 'text 🔴 Watch live: https://kick.com/x #tags' (link once, before the hashtags)."""
    from . import texts
    url = link(platform, name)
    if url.split("//", 1)[1].lower() in caption.lower():
        return caption
    tags = texts.TAG_RE.findall(caption)
    body = " ".join(texts.TAG_RE.sub(" ", caption).split())
    lbl = "🔴 Live pe" if texts.is_ro() else "🔴 Watch live:"
    return (f"{body} {lbl} {url} " + " ".join(tags)).strip()[:2000]


def apply(clip, caption):
    """-> (video path, caption) to post/export. Never blocks posting: any problem = original file, no card."""
    c = cfg()
    video = Path(clip["file"])
    if not c.get("stream_card", True):
        return video, caption
    src = source(clip)
    if not src:
        return video, caption
    plat, name = src
    if c.get("stream_card_link", True):
        caption = caption_with_link(caption, plat, name)
    try:
        st = stats(plat, name)
        png = video.with_suffix(".card.png")
        card_png(plat, name, st, png, c.get("stream_card_viewers", True), c.get("stream_card_followers", True))
        out = video.with_suffix(".card.mp4")
        t0 = float(c.get("hook_seconds", 2.5)) + 0.3          # after the hook box, which uses the same top area
        cmd = [tool("ffmpeg"), "-y", "-v", "error", "-i", str(video), "-loop", "1", "-framerate", "30", "-i", str(png),
               "-filter_complex", f"[1:v]format=rgba,fade=t=in:st={t0:.2f}:d=0.35:alpha=1[cd];"
                                  f"[0:v][cd]overlay=x={X}:y={Y}:shortest=1:format=auto[v]",
               "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
               "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "copy", "-movflags", "+faststart", str(out)]
        p = subprocess.run(cmd, capture_output=True, timeout=600,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if p.returncode or not out.exists() or out.stat().st_size < 1000:
            raise RuntimeError(p.stderr.decode("utf-8", "replace")[-300:])
        return out, caption
    except Exception as e:
        log.warning("stream card skipped (%s): %s", name, str(e)[:200])
        return video, caption
