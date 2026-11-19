"""Shows the app's internal Romanian status texts in English when ui_language is "en" (the default).
The log file stays as it is; only what the dashboard displays is translated."""
import re

_RULES = [(re.compile(a, re.I), b) for a, b in [
    (r"^astept bucati noi$", "waiting for new chunks"),
    (r"^pauză automată \(TikTok\) până la ", "auto pause (TikTok) until "),
    (r"^pauză postare (\d+)h: ", r"posting paused \1h: "),
    (r"^Auto-postare PORNITĂ \(ON\) \(Setări\)$", "Auto-post ON (Settings)"),
    (r"^Auto-postare OPRITĂ \(OFF\) \(Setări\)$", "Auto-post OFF (Settings)"),
    (r"^Auto-postare PORNITĂ \(ON\)", "Auto-post ON"),
    (r"^Auto-postare OPRITĂ \(OFF\)", "Auto-post OFF"),
    (r"^compilație TOP (\d+) gata \(clip #(\d+)\)$", r"TOP \1 compilation ready (clip #\2)"),
    (r"^⬇️ Descarc bucata$", "⬇️ Downloading chunk"),
    (r"^📝 Transcriere$", "📝 Transcribing"),
    (r"^🔎 Detectez momentele$", "🔎 Finding moments"),
    (r"^🤖 Verific cu AI$", "🤖 Checking with AI"),
    (r"^🎬 Randez clipul$", "🎬 Rendering clip"),
    (r"^📤 Postez pe TikTok$", "📤 Posting to TikTok"),
    (r"^⏳ Aștept$", "⏳ Waiting"),
    (r"^aștept placa video \(alt job transcrie acum\)…$", "waiting for the GPU (another job is transcribing)…"),
    (r"^pornesc Whisper…$", "starting Whisper…"),
    (r"^extrag sunetul…$", "extracting audio…"),
    (r"^(\d+) cuvinte, caut momente amuzante…$", r"\1 words, looking for funny moments…"),
    (r"^verific pe TikTok (\d+) postări întrerupte$", r"checking \1 interrupted posts on TikTok"),
    (r"^normalizez volumul \(-14 LUFS\)$", "normalizing loudness (-14 LUFS)"),
    (r"^randez clipurile…", "rendering clips…"),
    (r"^(#\S+) nu a devenit hashtag clickabil \(doar text\) - nu am postat$", r"\1 did not become a clickable hashtag (plain text) - not posted"),
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


DISPLAY_KEYS = ("label", "detail", "msg", "poster", "watcher", "worker", "error", "reason", "why")


def deep_en(obj, keys=DISPLAY_KEYS):
    """Translate only display texts (by key) inside nested dicts/lists. Internal codes the page compares
    (stage names, statuses) are left alone. No-op when ui_language is "ro"."""
    if not english():
        return obj

    def walk(o, key=None):
        if isinstance(o, dict):
            return {k: walk(v, k) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v, key) for v in o]
        if isinstance(o, str) and key in keys:
            return en(o)
        return o
    return walk(obj)
