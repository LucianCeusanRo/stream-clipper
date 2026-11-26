"""Posting accounts: several TikTok accounts and YouTube Shorts channels, each with its own login, hashtags,
daily limit and pace. Stored locally in data/accounts.json (never in git, never uploaded anywhere).

TikTok: each account has its own browser profile folder (data/accounts/<id>/browser_profile); the first
account keeps the old data/tiktok_profile so an existing login keeps working.
YouTube: official YouTube Data API with YOUR OWN OAuth client (see youtube_upload.py). Not connected ->
"export" mode: the clip + title/description are copied to data/exports/<id>/ for a manual upload.

Defaults are deliberately conservative (new accounts post little and slowly) to avoid spam flags.
"""
import re, threading, time
from .util import DATA, cfg, load_json, log, save_json

FILE = DATA / "accounts.json"
PLATFORMS = ("tiktok", "youtube", "facebook")
DEFAULTS = {
    "tiktok": {"daily_cap": 15, "interval_min": 30, "interval_max": 60, "visibility": "public"},
    # YouTube API: an upload costs 1600 of the default 10,000 daily quota units -> at most ~6 uploads/day
    "youtube": {"daily_cap": 5, "interval_min": 60, "interval_max": 120, "visibility": "public"},
    # Facebook Reels: export only. Meta's official Reels publishing API works for Pages, but needs a Meta app,
    # app review and a Page token - out of scope for a desktop app. The clip + caption are saved for a manual upload.
    "facebook": {"daily_cap": 10, "interval_min": 30, "interval_max": 60, "visibility": "public"},
}
LIMITS = {"daily_cap": (1, 100), "interval_min": (5, 1440), "interval_max": (5, 1440)}
_lk = threading.RLock()


def _clean_id(s):
    s = re.sub(r"[^a-z0-9_-]+", "-", str(s or "").lower()).strip("-")[:32]
    return s or f"acc{int(time.time())}"


def _tags(v):
    if isinstance(v, str):
        v = v.replace(",", " ").split()
    out = []
    for t in v or []:
        t = "#" + str(t).strip().lstrip("#")
        if len(t) > 1 and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:10]


def _norm(a):
    p = a.get("platform") if a.get("platform") in PLATFORMS else "tiktok"
    d = dict(DEFAULTS[p])
    d.update({k: v for k, v in a.items() if v is not None})
    d["platform"] = p
    d["id"] = _clean_id(d.get("id") or d.get("name"))
    d["name"] = str(d.get("name") or d["id"])[:60]
    d["enabled"] = bool(d.get("enabled", True))
    d["rotation"] = bool(d.get("rotation", True))
    d["hashtags"] = _tags(d.get("hashtags"))
    d["required_hashtag"] = (_tags([d["required_hashtag"]]) or [""])[0] if d.get("required_hashtag") else ""
    for k, (lo, hi) in LIMITS.items():
        try:
            d[k] = int(max(lo, min(hi, float(d[k]))))
        except (TypeError, ValueError):
            d[k] = DEFAULTS[p][k]
    if d["interval_max"] < d["interval_min"]:
        d["interval_max"] = d["interval_min"]
    if d.get("visibility") not in ("public", "private", "unlisted"):
        d["visibility"] = "public"
    return d


def all_accounts():
    """-> list of accounts. First run: one TikTok account 'main' built from the old global settings."""
    with _lk:
        data = load_json(FILE, None)
        if not isinstance(data, list):
            c = cfg()
            data = [{"id": "main", "name": "TikTok", "platform": "tiktok", "legacy_profile": True,
                     "daily_cap": min(int(c.get("daily_post_cap", 15) or 15), 45),
                     "interval_min": c.get("post_interval_min_minutes", 30), "interval_max": c.get("post_interval_max_minutes", 60),
                     "visibility": c.get("visibility", "public")}]
            save_json(FILE, [_norm(a) for a in data])
        return [_norm(a) for a in data]


def get(acc_id):
    return next((a for a in all_accounts() if a["id"] == acc_id), None)


def save_all(lst):
    with _lk:
        ids, out = set(), []
        for a in lst:
            a = _norm(a)
            while a["id"] in ids:
                a["id"] += "-2"
            ids.add(a["id"]); out.append(a)
        save_json(FILE, out)
        return out


def upsert(a):
    """Save one account. Without an id it is a NEW account (never overwrites an existing one with the same name)."""
    with _lk:
        lst = all_accounts()
        if not a.get("id"):
            base = _clean_id(a.get("name")); new = base; n = 2
            while any(b["id"] == new for b in lst):
                new = f"{base}-{n}"; n += 1
            a = dict(a, id=new)
        a = _norm(a)
        for i, b in enumerate(lst):
            if b["id"] == a["id"]:
                keep = {k: b[k] for k in ("legacy_profile",) if k in b}
                lst[i] = dict(b, **a, **keep)
                return save_all(lst)[i]
        lst.append(a)
        return save_all(lst)[-1]


def remove(acc_id):
    with _lk:
        lst = [a for a in all_accounts() if a["id"] != acc_id]
        if not lst:
            raise ValueError("trebuie să rămână cel puțin un cont")
        save_all(lst)


def profile_dir(acc):
    """Browser profile of a TikTok account (its own login session)."""
    if acc.get("legacy_profile"):
        return DATA / "tiktok_profile"
    return DATA / "accounts" / acc["id"] / "browser_profile"


def token_file(acc):
    return DATA / "accounts" / acc["id"] / "youtube_token.json"


def clear_token(acc):
    """Disconnect YouTube: remove the token AND its .bak copy (save_json keeps one)."""
    f = token_file(acc)
    for p in (f, f.with_name(f.name + ".bak"), f.with_suffix(".bak")):
        p.unlink(missing_ok=True)


def export_dir(acc):
    return DATA / "exports" / acc["id"]


def rotation_candidates(exclude=(), rotate=None):
    """Accounts a clip without a chosen account may go to (rotate OFF -> only the first enabled one)."""
    rotate = cfg().get("rotate", True) if rotate is None else rotate
    en = [a for a in all_accounts() if a["enabled"] and a["id"] not in exclude]
    if not rotate:
        return en[:1]
    sel = set(cfg().get("rotate_accounts") or [])
    return [a for a in en if a["rotation"] and (not sel or a["id"] in sel)] or en


def rotation_pick(posted_counts=None, last_used=None, ready=None, exclude=(), rotate=None):
    """Default target for a clip with no account chosen.
    Rotate ON (default): round-robin over the enabled rotation accounts - the one that posted least today, ties:
    the one used longest ago; accounts that can post right now (ready(acc) -> bool) are preferred, so a capped or
    "too soon" account never blocks the others. Rotate OFF: always the first enabled account.
    exclude = accounts that already have this clip (never the same clip twice on one account)."""
    cand = rotation_candidates(exclude, rotate)
    if not cand:
        return None
    posted_counts = posted_counts or {}
    last_used = last_used or {}
    order = sorted(cand, key=lambda a: (posted_counts.get(a["id"], 0), last_used.get(a["id"], 0)))
    if ready:
        for a in order:
            if ready(a):
                return a["id"]
    return order[0]["id"]


def public(acc):
    """What the dashboard shows (adds connection state, hides nothing secret because nothing secret is stored here)."""
    d = dict(acc)
    if acc["platform"] == "tiktok":
        d["connected"] = profile_dir(acc).exists()
        d["mode"] = "browser"
    elif acc["platform"] == "facebook":
        d["connected"] = False
        d["mode"] = "export"
    else:
        d["connected"] = token_file(acc).exists()
        d["mode"] = "api" if d["connected"] else "export"
    return d
