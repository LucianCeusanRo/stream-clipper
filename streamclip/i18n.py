"""Shows the app's internal Romanian status texts in English when ui_language is "en" (the default).
The log file stays as it is; only what the dashboard displays is translated."""
import re

_RULES = [(re.compile(a, re.I), b) for a, b in [
    (r"^astept bucati noi$", "waiting for new chunks"),
    (r"^toate bucățile descărcate sunt procesate; aștept următoarea$", "all downloaded chunks are processed; waiting for the next one"),
    (r"^Whisper eliberat din memorie", "Whisper freed from memory"),
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
    (r"nu esti logat pe TikTok: apasa Login la contul din Conturi", "not logged in to TikTok: press Log in on the account (Accounts)"),
    (r"^exportat pentru upload manual$", "exported for manual upload"),
    (r"limitare YouTube: cota zilnică API depășită", "YouTube limit: daily API quota used up"),
    (r"^postare esuata \((.*?)\): ", r"posting failed (\1): "),
    (r"^(#\S+) nu a devenit hashtag clickabil \(doar text\) - nu am postat$", r"\1 did not become a clickable hashtag (plain text) - not posted"),
    (r"^procesez ", "processing "),
    (r"^postez acum$", "posting now"),
    (r"^postez ", "posting "),
    (r"^pauza$", "paused"),
    (r"^nimic de postat \(auto-postare ON\)$", "nothing to post (auto-post ON)"),
    (r"^nimic de postat \(apasa Posteaza pe un clip\)$", "nothing to post (press Post on a clip)"),
    (r"^ore de liniste$", "quiet hours"),
    (r"^limita zilnica atinsa", "daily limit reached"),
    (r"^urmatoarea postare la ", "next post at "),
    (r": limita zilnica atinsa", ": daily limit reached"),
    (r": urmatoarea postare la ", ": next post at "),
    (r": pauză până la ", ": paused until "),
    (r"^cont dezactivat$", "account disabled"),
    (r"^niciun cont activ$", "no enabled account"),
    (r"aplicația s-a închis în timpul uploadului YouTube - verifică în YouTube Studio",
     "the app closed during the YouTube upload - check YouTube Studio"),
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


ERRORS_EN = {
    "actiune necunoscuta": "unknown action", "clip inexistent": "clip not found",
    "cerere respinsa (token lipsa/gresit) - reincarca pagina": "request rejected (missing/wrong token) - reload the page",
    "clipul e deja postat": "this clip is already posted", "clipul se posteaza acum": "this clip is being posted right now",
    "clipul e sters": "this clip was deleted", "cont YouTube inexistent": "YouTube account not found",
    "cont inexistent": "account not found", "fisier in afara folderului de date": "file outside the data folder",
    "font necunoscut": "unknown font", "host nepermis": "host not allowed", "id invalid": "invalid id",
    "intervalul minim trebuie sa fie cel putin 1 minut": "the minimum interval must be at least 1 minute",
    "nu exista": "not found", "numarul de hashtag-uri trebuie sa fie intre 1 si 10": "hashtag count must be between 1 and 10",
    "ordine necunoscuta": "unknown order", "pragul viral trebuie sa fie intre 0 si 100": "viral threshold must be between 0 and 100",
    "ritm necunoscut": "unknown pace", "similaritatea trebuie sa fie intre 0.5 si 1.0": "similarity must be between 0.5 and 1.0",
    "trebuie să rămână cel puțin un cont": "at least one account must remain",
    "cerere de conectare expirată sau necunoscută - apasă din nou Conectează": "connect request expired or unknown - press Connect again",
    "Google nu a trimis refresh_token - încearcă din nou": "Google did not send a refresh token - try again",
    "lipsește youtube_client_secret în config.yaml (clientul tău OAuth Google, tip Desktop app)":
        "youtube_client_secret is missing in config.yaml (your own Google OAuth client, type Desktop app)",
}


def english():
    from .util import cfg
    return str(cfg().get("ui_language") or "en").lower() != "ro"


def en(text):
    """Romanian status text -> English (unknown texts are returned unchanged)."""
    if not text or not isinstance(text, str):
        return text
    if text in ERRORS_EN:
        return ERRORS_EN[text]
    if text.startswith("re-tăierea a eșuat: "):
        return "re-cut failed: " + text[20:]
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
