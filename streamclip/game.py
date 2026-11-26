"""Which game is being played? Used ONLY for clip titles, descriptions and hashtags (never for on-video text).

Order: the clip's own game (you can set it in the app) > the stream's game from the platform
(Twitch / Kick category, yt-dlp metadata) > a known game named in the stream title > the "Default game" setting
> nothing (neutral wording and #gaming #clips). Never GTA 6 by default.

Names are normalised to the official name: well-known games through a built-in table (CS2 -> "Counter-Strike 2",
#CS2), anything else through the public Steam store search. Steam answers are cached in data/game_cache.json;
offline, the platform's own category name is used as it is. Nothing here ever raises.
"""
import re, threading, time
from urllib.parse import quote, urlparse
import requests
from .util import DATA, load_json, log, save_json

CACHE = DATA / "game_cache.json"
VIDEO_GAMES = DATA / "video_games.json"
_lk = threading.Lock()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StreamClipper"
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"      # Twitch's own public web client id (same one yt-dlp uses)
NEUTRAL_TAGS = ["#gaming", "#clips"]

# categories that are not a game: no game name, neutral wording
NOT_A_GAME = re.compile(
    r"^(just chatting|irl|talk shows?( & podcasts)?|podcasts?|music|art|asmr|sports?|special events|pools?,? hot tubs?.*|"
    r"travel & outdoors|food & drink|science & technology|software and game development|slots|gambling|casino|"
    r"gaming|games?|videogames?|video games?|entertainment|people & blogs|news & politics|education|howto & style|"
    r"comedy|film & animation|autos & vehicles|pets & animals|nonprofits & activism|shows|\s*)$", re.I)

# (regex on category/title, official name, hashtag)
KNOWN = [
    (r"counter[- ]?strike|\bcs ?2\b|\bcs:?go\b|\bcsgo\b", "Counter-Strike 2", "#CS2"),
    (r"call of duty|\bcod\b|warzone|black ops|modern warfare", "Call of Duty", "#CallOfDuty"),
    (r"the finals\b", "THE FINALS", "#TheFinals"),
    (r"\bskate ?3\b", "skate 3", "#Skate3"),
    (r"\bskate\.(?!\w)", "skate.", "#skate"),
    (r"team fortress|\btf2\b", "Team Fortress 2", "#TF2"),
    (r"grand theft auto (vi|6)\b|\bgta ?(vi|6)\b", "Grand Theft Auto VI", "#GTA6"),
    (r"grand theft auto v\b|\bgta ?v\b|\bgta ?5\b|gta online", "Grand Theft Auto V", "#GTAV"),
    (r"fortnite", "Fortnite", "#Fortnite"),
    (r"valorant", "VALORANT", "#Valorant"),
    (r"minecraft", "Minecraft", "#Minecraft"),
    (r"apex legends", "Apex Legends", "#ApexLegends"),
    (r"league of legends", "League of Legends", "#LeagueOfLegends"),
    (r"dota ?2", "Dota 2", "#Dota2"),
    (r"overwatch", "Overwatch 2", "#Overwatch"),
    (r"rainbow six", "Tom Clancy's Rainbow Six Siege", "#RainbowSix"),
    (r"rocket league", "Rocket League", "#RocketLeague"),
    (r"marvel rivals", "Marvel Rivals", "#MarvelRivals"),
    (r"escape from tarkov|\btarkov\b", "Escape from Tarkov", "#Tarkov"),
    (r"battlefield", "Battlefield", "#Battlefield"),
    (r"pubg|battlegrounds", "PUBG: BATTLEGROUNDS", "#PUBG"),
    (r"^rust$", "Rust", "#Rust"),
    (r"roblox", "Roblox", "#Roblox"),
    (r"ea sports fc|fifa", "EA SPORTS FC", "#EAFC"),
    (r"elden ring", "Elden Ring", "#EldenRing"),
    (r"red dead", "Red Dead Redemption 2", "#RDR2"),
    (r"euro truck", "Euro Truck Simulator 2", "#ETS2"),
    (r"world of warcraft", "World of Warcraft", "#WoW"),
]
_KNOWN = [(re.compile(rx, re.I), name, tag) for rx, name, tag in KNOWN]


def is_game_name(s):
    s = " ".join(str(s or "").split())
    return bool(s) and not NOT_A_GAME.match(s)


def tag_for(name):
    """'#CS2' for Counter-Strike 2, '#TheFinals' for THE FINALS, '#Hades' ... '' when there is no game."""
    if not is_game_name(name):
        return ""
    for rx, nm, tag in _KNOWN:
        if nm.lower() == str(name).lower() or rx.search(str(name)):
            return tag
    words = re.findall(r"[A-Za-z0-9]+", str(name))
    t = "".join(w[:1].upper() + w[1:] for w in words)
    return ("#" + t[:24]) if len(t) >= 2 else ""


def from_title(title):
    """A well-known game named in the stream title -> official name, else ''."""
    for rx, name, _ in _KNOWN:
        if rx.search(str(title or "")):
            return name
    return ""


def _cache():
    c = load_json(CACHE, {}) if CACHE.exists() else {}
    return c if isinstance(c, dict) else {}


def steam_name(term, timeout=4):
    """Official name from the public Steam store search; '' if nothing matches or we are offline (cached)."""
    key = " ".join(str(term).lower().split())
    if not key:
        return ""
    with _lk:
        c = _cache()
        hit = c.get(key)
        if hit is not None and (hit.get("name") or time.time() - hit.get("t", 0) < 7 * 86400):
            return hit.get("name") or ""
    try:
        r = requests.get("https://store.steampowered.com/api/storesearch/",
                         params={"term": key, "cc": "us", "l": "en"}, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        items = [i for i in (r.json().get("items") or []) if i.get("type") == "app" and i.get("name")]
    except Exception as e:
        log.debug("steam lookup offline/failed (%s)", str(e)[:80])
        return ""                                # not cached: try again next time
    norm = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower())
    name = ""
    for i in items:
        if norm(i["name"]) == norm(key):
            name = i["name"]; break
    if not name and items and norm(key) in norm(items[0]["name"]) and len(norm(key)) >= 4:
        name = items[0]["name"]                  # e.g. "the finals" -> "THE FINALS"
    with _lk:
        c = _cache(); c[key] = {"name": name, "t": time.time()}
        try:
            save_json(CACHE, c)
        except OSError:
            pass
    return name


def normalize(raw, lookup=True):
    """Platform category / typed name -> official name. '' = not a game (or empty)."""
    raw = " ".join(str(raw or "").split())[:80]
    if not is_game_name(raw):
        return ""
    for rx, name, _ in _KNOWN:
        if rx.search(raw):
            return name
    if lookup:
        return steam_name(raw) or raw           # unknown to Steam (or offline): keep the platform's own name
    return raw


# ---------- metadata ----------
def from_info(info):
    """(official name, source) from a yt-dlp info dict: game / categories / chapters, then the title."""
    info = info or {}
    cands = [info.get("game")] + list(info.get("categories") or []) + [
        ch.get("title") for ch in (info.get("chapters") or []) if isinstance(ch, dict)]
    for raw in cands:
        n = normalize(raw)
        if n:
            return n, "metadata"
    n = from_title(info.get("title"))
    return (n, "title") if n else ("", "")


def _twitch_game(url, timeout=6):
    u = urlparse(url)
    path = [p for p in u.path.split("/") if p]
    try:
        if "videos" in path and path[-1].isdigit():
            q = 'query{video(id:"%s"){game{displayName}}}' % path[-1]
            pick = lambda d: ((d.get("video") or {}).get("game") or {}).get("displayName")
        elif path and re.fullmatch(r"\w{3,25}", path[0]):
            q = 'query{user(login:"%s"){stream{game{displayName}} lastBroadcast{game{displayName}}}}' % path[0].lower()
            def pick(d):
                us = d.get("user") or {}
                return (((us.get("stream") or {}).get("game") or {}).get("displayName")
                        or ((us.get("lastBroadcast") or {}).get("game") or {}).get("displayName"))
        else:
            return ""
        r = requests.post("https://gql.twitch.tv/gql", json={"query": q}, headers={"Client-ID": TWITCH_CLIENT_ID},
                          timeout=timeout)
        return pick((r.json().get("data") or {})) or ""
    except Exception as e:
        log.debug("twitch game lookup failed (%s)", str(e)[:80])
        return ""


def _kick_game(url, timeout=6):
    path = [p for p in urlparse(url).path.split("/") if p]
    if not path or not re.fullmatch(r"[\w-]{2,40}", path[0]):
        return ""
    try:
        r = requests.get(f"https://kick.com/api/v2/channels/{quote(path[0])}", headers={"User-Agent": UA}, timeout=timeout)
        j = r.json()
        live = j.get("livestream") or {}
        cats = live.get("categories") or []
        return (cats[0].get("name") if cats else None) or (j.get("recent_categories") or [{}])[0].get("name") or ""
    except Exception as e:
        log.debug("kick game lookup failed (%s)", str(e)[:80])
        return ""


def from_url(url):
    """Game from the platform's public API for Twitch / Kick links. '' when unknown or offline."""
    host = (urlparse(str(url)).hostname or "").lower()
    raw = _twitch_game(url) if host.endswith("twitch.tv") else _kick_game(url) if host.endswith("kick.com") else ""
    return normalize(raw)


def detect(info=None, url=None):
    """-> (official game name or '', source). yt-dlp info first, then the platform API, then the title."""
    n, src = from_info(info)
    if n and src == "metadata":
        return n, src
    if url:
        n2 = from_url(url)
        if n2:
            return n2, "platform"
    return (n, src) if n else ("", "")


# ---------- per stream / per clip ----------
def remember(vid, game, src=""):
    with _lk:
        d = load_json(VIDEO_GAMES, {}) if VIDEO_GAMES.exists() else {}
        d = d if isinstance(d, dict) else {}
        d[str(vid)] = {"game": game or "", "src": src}
        if len(d) > 500:
            for k in list(d)[:len(d) - 500]:
                d.pop(k)
        try:
            save_json(VIDEO_GAMES, d)
        except OSError:
            pass


def remember_from(vid, info=None, url=None):
    """Detect the game of a stream/video and keep it for its clips. Returns the name ('' = unknown)."""
    try:
        g, src = detect(info, url)
    except Exception as e:
        log.debug("game detection failed: %s", str(e)[:100]); g, src = "", ""
    remember(vid, g, src)
    if g:
        log.info("joc detectat pentru %s: %s (%s)", vid, g, src)
    return g


def for_video(vid, title=None):
    d = load_json(VIDEO_GAMES, {}) if VIDEO_GAMES.exists() else {}
    g = ((d or {}).get(str(vid)) or {}).get("game") or ""
    return g or from_title(title)


_LEGACY_DEFAULT = re.compile(r"^\s*(gta\s*(6|vi)|grand theft auto (6|vi))\s*$", re.I)


def default_game(c=None):
    """The 'Default game or topic' setting; the old built-in default 'GTA 6' counts as not set."""
    if c is None:
        from .util import cfg
        c = cfg()
    g = " ".join(str(c.get("game") or "").split())
    return "" if (not g or _LEGACY_DEFAULT.match(g)) else g


def effective(clip_game=None, vid=None, title=None, c=None):
    """Game used for one clip's title/hashtags: clip > stream > title > default setting > '' (neutral)."""
    for g in (clip_game, for_video(vid, title) if vid else from_title(title), default_game(c)):
        g = " ".join(str(g or "").split())
        if g and is_game_name(g):
            return g
    return ""


def hashtags(game):
    """[#CS2] for a known game, [#gaming, #clips] when the game is unknown."""
    t = tag_for(game)
    return [t] if t else list(NEUTRAL_TAGS)
