"""Shows the app's internal Romanian status texts in English when ui_language is "en" (the default).
The log file stays as it is; only what the dashboard displays is translated."""
import re

_RULES = [(re.compile(a, re.I), b) for a, b in [
    (r"^astept bucati noi$", "waiting for new chunks"),
    (r"^procesez ", "processing "),
    (r"^postez ", "posting "),
    (r"^pauza$", "paused"),
    (r"^nimic de postat \(auto-postare ON\)$", "nothing to post (auto-post ON)"),
    (r"^nimic de postat \(apasa Posteaza pe un clip\)$", "nothing to post (press Post on a clip)"),
    (r"^ore de liniste$", "quiet hours"),
    (r"^limita zilnica atinsa", "daily limit reached"),
    (r"^urmatoarea postare la ", "next post at "),
    (r"^astept$", "waiting"),
    (r"^pornesc$", "starting"),
    (r"^oprit \(apasa Start\)$", "stopped (press Start)"),
    (r"^niciun canal setat.*$", "no channel set (Settings); you can still generate clips from any link"),
    (r"^verific daca canalul e live\.\.\.$", "checking if the channel is live..."),
    (r"^inregistrez: ", "recording: "),
    (r"^canalul nu e live acum, verific din nou in curand$", "channel not live, checking again soon"),
    (r"^în așteptare$", "queued"),
    (r"^citesc linkul…$", "reading the link…"),
    (r"^descarc… ", "downloading… "),
    (r"^e LIVE: înregistrez (\d+) minute…$", r"it's LIVE: recording \1 minutes…"),
    (r"^analizez bucata (\d+)/(\d+) \(transcriere \+ momente\)…$", r"analysing chunk \1/\2 (transcript + moments)…"),
    (r"^gata: (\d+) clipuri în galerie", r"done: \1 clips in the gallery"),
    (r"\(ai cerut (\d+), dar doar atâtea momente bune am găsit\)", r"(you asked for \1, these are all the good moments found)"),
    (r"strigat/spike volum", "scream/volume spike"),
    (r"chat explodeaza", "chat exploding"),
    (r"\bras_audio\b", "laughter (audio)"),
    (r"\bras\b", "laughter"),
    (r"\binjuratura\b", "swearing"),
    (r"\bexclamatie\b", "exclamation"),
    (r"\bactiune\b", "action"),
    (r"\benergie\b", "energy"),
]]

LABELS_EN = {"hook": "Hook (first 2 s)", "emotie": "Emotion / volume (screams, laughter)",
             "cuvinte": "Keywords (laughter, rage, \u201cno way\u201d)", "chat": "Chat exploding",
             "durata": "Good length (20–35 s ideal)", "ai": "AI score (LLM)"}


def english():
    from .util import cfg
    return str(cfg().get("ui_language") or "en").lower() != "ro"


def en(text):
    """Romanian status text -> English (unknown texts are returned unchanged)."""
    if not text or not isinstance(text, str):
        return text
    for rx, rep in _RULES:
        text = rx.sub(rep, text)
    return text
