"""Hooks (on-screen, first 2 s) and titles used when no LLM is configured. English, or Romanian when language: ro."""
import random, re
from .detect import fold

# {name} = streamer_name from config.yaml (empty -> "streamerul"), {game} = game from config.yaml.
HOOKS = {
    "ras_audio": ["{NAME} A MURIT DE RÂS 😂", "N-AM MAI RÂS AȘA DE MULT", "CE A FOST ASTA? 😂"],
    "ras": ["{NAME} A MURIT DE RÂS 😂", "N-AM MAI RÂS AȘA DE MULT", "ASTA M-A TERMINAT 💀", "CE A FOST ASTA? 😂"],
    "injuratura": ["{NAME} A LUAT-O RAZNA 🤬", "NERVI MAXIMI LA {GAME}", "NU MAI POATE 😤", "RAGE MAXIM ÎN {GAME}"],
    "exclamatie": ["NU SE POATE CE A PĂȚIT", "REACȚIA LUI {NAME} 😱", "STAI SĂ VEZI FINALUL", "NIMENI NU SE AȘTEPTA"],
    "giveaway": ["GIVEAWAY PE LIVE 🎁", "CINE CÂȘTIGĂ PREMIUL?", "A ANUNȚAT PREMIUL 🎁"],
    "actiune": ["CEA MAI TARE FAZĂ DIN {GAME}", "{GAME} = HAOS TOTAL", "{GAME} PE LIVE E ALTCEVA"],
    "chat": ["CHATUL L-A ENERVAT 😂", "{NAME} VS CHATUL 😂", "CE I-A ZIS CHATUL"],
    "_": ["MOMENT DE AUR DIN LIVE", "STAI PÂNĂ LA FINAL 😂", "ASTA TREBUIA CLIPUITĂ"],
}
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


def fill(t, c=None):
    """Put the streamer name / game from config into a template."""
    if c is None:
        from .util import cfg
        c = cfg()
    ro = is_ro(c)
    name = str(c.get("streamer_name") or "").strip() or ("streamerul" if ro else "the streamer")
    game = str(c.get("game") or "").strip() or ("jocul" if ro else "the game")
    return (t.replace("{NAME}", name.upper()).replace("{GAME}", game.upper())
             .replace("{Name}", name[:1].upper() + name[1:]).replace("{name}", name).replace("{game}", game))



HOOKS_EN = {
    "ras_audio": ["{NAME} COULDN'T STOP LAUGHING 😂", "I HAVEN'T LAUGHED THIS HARD", "WHAT WAS THAT? 😂"],
    "ras": ["{NAME} COULDN'T STOP LAUGHING 😂", "THIS ONE ENDED ME 💀", "WHAT WAS THAT? 😂"],
    "injuratura": ["{NAME} LOST IT 🤬", "{GAME} RAGE MOMENT", "HE CAN'T TAKE IT ANYMORE 😤"],
    "exclamatie": ["NO WAY THIS HAPPENED", "{NAME}'S REACTION 😱", "WAIT FOR THE END", "NOBODY SAW THIS COMING"],
    "giveaway": ["GIVEAWAY ON STREAM 🎁", "WHO WINS THE PRIZE?"],
    "actiune": ["BEST {GAME} MOMENT SO FAR", "{GAME} = PURE CHAOS", "{GAME} ON STREAM HITS DIFFERENT"],
    "chat": ["CHAT WENT TOO FAR 😂", "{NAME} VS CHAT 😂", "WHAT CHAT SAID"],
    "_": ["GOLDEN MOMENT FROM THE STREAM", "WAIT FOR IT 😂", "THIS HAD TO BE CLIPPED"],
}
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


def new_title(cat, words_rel=(), avoid=(), rnd=random):
    """A title different from the ones in `avoid` (used by '🔄 Refă textul')."""
    T = _pick(TITLES, TITLES_EN)
    pool = [fill(t) for t in list(T.get(cat, T["_"])) + T["_"][:3]]
    q = quote(list(words_rel))
    if q:
        pool += [fill(t).replace("{q}", q) for t in _pick(QUOTE_TITLES, QUOTE_TITLES_EN)]
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


def pick_hashtags(c, rnd=random):
    """required hashtag (if any) + your fixed hashtags + a few random popular ones, max `hashtags_max` in total."""
    fixed = order_tags(c.get("hashtags") or [])
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


def make(cand, words_rel, rnd=random):
    cat = category(cand.get("cats", []))
    hooks, titles = _pick(HOOKS, HOOKS_EN), _pick(TITLES, TITLES_EN)
    hook = quote_hook(words_rel, cand["peak"] - cand["start"]) or fill(rnd.choice(hooks.get(cat, hooks["_"])))
    return hook, fill(rnd.choice(titles.get(cat, titles["_"]))), cat
