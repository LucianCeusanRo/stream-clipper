"""Titles used when no LLM is configured. (On-video hooks are only real quotes of the streamer; see make().) English, or Romanian when language: ro."""
import random, re
from .detect import fold

# {name} = streamer_name from config.yaml (empty -> "streamerul"), {game} = game from config.yaml.
TITLES = {
    "ras_audio": ["{Name} n-a mai putut de râs 😂", "Cel mai amuzant moment din live 😂", "Am plâns de râs la asta 😭",
                  "Râsul ăsta e contagios 😂", "Nu te uita dacă nu vrei să râzi 😂"],
    "ras": ["{Name} n-a mai putut de râs 😂", "Am plâns de râs la asta 😭", "Cel mai amuzant moment din live 😂",
            "Asta m-a terminat 💀", "Nu te uita dacă nu vrei să râzi 😂", "Am dat replay de 10 ori 😭"],
    "injuratura": ["{Name} și-a pierdut răbdarea în {game} 🤬", "Nervi maximi la {game} 😤", "Rage maxim pe live 💀",
                   "{game} l-a scos din minți 🤬", "Când {game} nu te ascultă 😤"],
    "exclamatie": ["Reacția e de nota 10 😱", "Nu se aștepta nimeni la asta 😳", "{Name} a rămas fără cuvinte 😂",
                   "Uită-te până la final 😳", "Fața lui când a văzut asta 😱", "Nu se poate ce s-a întâmplat 😭"],
    "giveaway": ["Giveaway pe live 🎁", "Cine câștigă premiul? 🎮", "A anunțat premiul 🎁"],
    "actiune": ["{game} pe live = haos total 🔥", "{game} cu {name} e altă poveste 😂", "Cea mai tare fază din {game} 🔥",
                "Așa se joacă {game} în România 🇷🇴", "A stricat {game} 😂"],
    "chat": ["Chatul l-a terminat 😂", "{Name} vs chat, runda 1 🥊", "Chatul n-are milă 😂",
             "Citește chatul și regretă 💀", "Chatul a avut dreptate 😂"],
    "_": ["Momente tari din live 🔥", "Live-ul ăsta e istorie 🔥", "POV: ești în chat 😂", "Stai până la final 😂"],
}
# viral title patterns built around a short quote actually said on stream ("„NU SE POATE, FRATE!” 😭")
QUOTE_TITLES = ["„{q}” 😭", "„{q}” – {Name} 😂", "{Name}: „{q}” 💀", "Când {name} zice „{q}” 😂"]


def fill(t, c=None, game=None):
    """Put the streamer name / game into a template. `game` = the game of this clip ('' = unknown -> neutral wording);
    None = only the 'Default game' setting."""
    if c is None:
        from .util import cfg
        c = cfg()
    ro = is_ro(c)
    name = str(c.get("streamer_name") or "").strip() or ("streamerul" if ro else "the streamer")
    if game is None:
        from . import game as _g
        game = _g.default_game(c)
    game = str(game or "").strip() or ("jocul" if ro else "the game")
    return (t.replace("{NAME}", name.upper()).replace("{GAME}", game.upper())
             .replace("{Name}", name[:1].upper() + name[1:]).replace("{name}", name).replace("{game}", game))



TITLES_EN = {
    "ras_audio": ["{Name} couldn't stop laughing 😂", "Funniest moment of the stream 😂", "That laugh is contagious 😂"],
    "ras": ["{Name} couldn't stop laughing 😂", "I cried laughing at this 😭", "Funniest moment of the stream 😂",
            "Replayed this 10 times 😭"],
    "injuratura": ["{Name} lost all patience in {game} 🤬", "{game} rage on stream 😤", "When {game} doesn't listen 😤"],
    "exclamatie": ["That reaction is a 10/10 😱", "Nobody expected this 😳", "{Name} was speechless 😂",
                   "Watch till the end 😳"],
    "giveaway": ["Giveaway on stream 🎁", "Who wins the prize? 🎮"],
    "actiune": ["{game} on stream = pure chaos 🔥", "Best {game} moment so far 🔥", "{Name} broke {game} 😂"],
    "chat": ["Chat destroyed {name} 😂", "{Name} vs chat, round 1 🥊", "Chat was right 😂"],
    "_": ["Best moments from the stream 🔥", "This stream was history 🔥", "POV: you're in chat 😂"],
}
QUOTE_TITLES_EN = ["\u201c{q}\u201d 😭", "\u201c{q}\u201d – {Name} 😂", "{Name}: \u201c{q}\u201d 💀"]
EXCLAIM_RO = r"(?i)(nu |ce |doamne|frate|bă|băi|hai|gata|stai|aoleu|mamă|vai)"
EXCLAIM_EN = r"(?i)(no |what|oh my|bro|dude|wait|let's go|come on|why|stop)"


def is_ro(c=None):
    if c is None:
        from .util import cfg
        c = cfg()
    return str(c.get("language") or "").lower() == "ro"


def _pick(ro_table, en_table, c=None):
    return ro_table if is_ro(c) else en_table

PRIORITY = ["ras", "ras_audio", "giveaway", "injuratura", "chat", "exclamatie", "actiune"]


def category(cats):
    for p in PRIORITY:
        if p in cats:
            return p
    return "_"


def quote_hook(words, peak_rel):
    """Short phrase he actually shouted near the peak, as a quote hook: „NU SE POATE, FRATE!”"""
    near = [w for w in words if abs(w["s"] - peak_rel) < 4]
    if not (3 <= len(near) <= 14):
        return None
    loud = " ".join(w["w"] for w in near[:6]).strip(" ,.")
    if len(loud) < 8 or len(loud) > 40:
        return None
    if not re.search(EXCLAIM_RO if is_ro() else EXCLAIM_EN, loud):
        return None
    return f"„{loud.upper()}”" if is_ro() else f"\u201c{loud.upper()}\u201d"


def quote(words_rel, max_words=6):
    """A short exclamation from the clip, usable inside a title."""
    txt = " ".join(w["w"] for w in words_rel)
    for sent in re.split(r"(?<=[.!?])\s+", txt):
        sent = sent.strip(" ,")
        n = len(sent.split())
        if 2 <= n <= max_words and re.search(r"(?i)(nu se poate|doamne|frate|aoleu|mamă|vai|bă|băi|gata|ce-i asta|ce faci|"
                                              r"no way|oh my god|what the|let's go|come on|bro|dude)", sent):
            return sent.rstrip(".")
    return None


def new_title(cat, words_rel=(), avoid=(), rnd=random, game=None):
    """A title different from the ones in `avoid` (used by '🔄 Refă textul')."""
    T = _pick(TITLES, TITLES_EN)
    pool = [fill(t, game=game) for t in list(T.get(cat, T["_"])) + T["_"][:3]]
    q = quote(list(words_rel))
    if q:
        pool += [fill(t, game=game).replace("{q}", q) for t in _pick(QUOTE_TITLES, QUOTE_TITLES_EN)]
    fresh = [t for t in pool if t not in set(avoid)] or pool
    return rnd.choice(fresh)


# ---------- hashtags: optional `required_hashtag` ALWAYS first (e.g. a clipping campaign tag) ----------
TAG_RE = re.compile(r"(?<![\w#])#\w+")


def norm_tag(t):
    t = str(t).strip().strip(",;")
    t = "#" + t.lstrip("#")
    return t if re.fullmatch(r"#\w+", t) else ""


def required_tag():
    """The campaign hashtag from config.yaml (`required_hashtag`), or "" when none is set."""
    from .util import cfg
    return norm_tag(cfg().get("required_hashtag") or "") if cfg().get("required_hashtag") else ""


def order_tags(tags):
    """Dedupe (case-insensitive); the required hashtag (if any) goes first."""
    req = required_tag()
    out, seen = ([req], {req.lower()}) if req else ([], set())
    for t in tags:
        t = norm_tag(t)
        if t and t.lower() not in seen:
            seen.add(t.lower()); out.append(t)
    return out


_GTA_TAG = re.compile(r"^#gta(6|vi|5|v)?$", re.I)


def pick_hashtags(c, rnd=random, game=None):
    """required hashtag (if any) + the game's hashtag (#CS2) + your fixed hashtags + a few random popular ones,
    max `hashtags_max` in total. Unknown game = neutral (#gaming #clips) unless you set your own hashtags.
    An old built-in #gta6 is dropped unless the clip really is GTA."""
    from . import game as _g
    gtag = _g.tag_for(game)
    mine = [t for t in (c.get("hashtags") or []) if gtag.lower().startswith("#gta") or not _GTA_TAG.match(norm_tag(t))]
    base = ([gtag] if gtag else []) + mine
    fixed = order_tags(base if (gtag or mine) else _g.NEUTRAL_TAGS)
    mx = max(1, int(c.get("hashtags_max", 5)))
    pool = [t for t in order_tags(c.get("extra_hashtags") or []) if t.lower() not in {f.lower() for f in fixed}]
    rnd.shuffle(pool)
    return (fixed + pool)[:max(mx, 1)] if len(fixed) <= mx else fixed


def finalize_caption(text):
    """Text first, then hashtags (required hashtag first, if set). Hashtags already in the text are kept (moved
    to the end)."""
    text = str(text or "")
    found = TAG_RE.findall(text)
    body = " ".join(TAG_RE.sub(" ", text).split())
    return (body + " " + " ".join(order_tags(found))).strip()[:2000]


def make(cand, words_rel, rnd=random, game=None):
    """-> (hook, title, category). The hook is burned into the video, so it is ONLY words the streamer really said
    (a short quote); when there is none the clip simply has no hook box. Game names go in titles/hashtags only."""
    cat = category(cand.get("cats", []))
    titles = _pick(TITLES, TITLES_EN)
    hook = quote_hook(words_rel, cand["peak"] - cand["start"]) or ""
    return hook, fill(rnd.choice(titles.get(cat, titles["_"])), game=game), cat
