"""Optional LLM step (any OpenAI-compatible API: OpenAI, xAI, Groq, OpenRouter, DeepSeek, local Ollama/LM Studio).

Configure with environment variables (or the .env file next to config.yaml):
  LLM_API_KEY   key (leave empty for local Ollama)
  LLM_BASE_URL  e.g. https://api.openai.com/v1 | https://api.x.ai/v1 | https://api.groq.com/openai/v1 |
                https://openrouter.ai/api/v1 | http://localhost:11434/v1 (Ollama)
  LLM_MODEL     e.g. gpt-4o-mini | grok-3-mini | llama-3.3-70b-versatile | qwen2.5:14b
Without them the program works fully on heuristics + templates.
"""
import json, os, re
import requests
from . import texts
from .util import ROOT, log

# {name}/{game}/{NAME} are filled from config.yaml (streamer_name, game) by texts.fill()
PROMPT_JUDGE = """Ești editorul unei pagini de TikTok cu cele mai amuzante momente din live-urile lui {name}
(streamer, joacă {game}). Un clip bun: moment AMUZANT, reacție puternică, se înțelege fără context,
hook în prima secundă, subtitrări mari.

Primești transcrierea (română, cu secunde) a unui moment candidat și semnalele detectate.
Evaluează cât de viral/amuzant e pe TikTok în România: glume, nervi/rage, țipete, reacții neașteptate,
injurături amuzante, conversații/glume cu chatul, hype de giveaway, faze tari din {game}.
Penalizează: momente plictisitoare, liniște, citit donații fără reacție, reclame/sponsori, fără poantă.

Răspunde DOAR cu JSON:
{"scor": 0-10,
 "categorie": "amuzant|rage|reactie|giveaway|gta|chat|plictisitor",
 "start": secunda de început recomandată (ca hook-ul să fie în primele 1-2 secunde),
 "end": secunda de final (după poantă, clipul 20-60s),
 "hook": "text scurt pe ecran, MAJUSCULE, max 7 cuvinte, cu diacritice, ex: {NAME} A LUAT-O RAZNA 😂",
 "titlu": "descriere TikTok scurtă și catchy în română, max 90 caractere, 1-2 emoji, fără hashtag-uri",
 "corecturi": [{"i": index_cuvant, "w": "cuvântul corectat"}]}
La "corecturi" repară doar greșelile clare de transcriere (diacritice ș ț ă â î, nume: {name}, {game},
argou românesc). Nu schimba sensul. Lista poate fi goală."""


# English prompts (used unless language: ro). JSON keys stay the same so the parser is shared.
PROMPT_JUDGE_EN = """You edit a short-video page with the best moments from {name}'s streams ({game}).
A good clip: a funny or intense moment, a strong reaction, understandable without context, a hook in the first second.

You get the transcript of a candidate moment (with seconds) and the detected signals. Rate how well it would do
as a short clip: jokes, rage, screams, unexpected reactions, banter with chat, giveaway hype, big game moments.
Penalize: boring parts, silence, reading donations without a reaction, ads/sponsors, no payoff.

Reply ONLY with JSON:
{"scor": 0-10,
 "categorie": "amuzant|rage|reactie|giveaway|gta|chat|plictisitor",
 "start": recommended start second (so the hook lands in the first 1-2 seconds),
 "end": end second (after the payoff, clip 20-60 s),
 "hook": "short on-screen text, UPPERCASE, max 7 words, in the language of the transcript",
 "titlu": "short catchy description in the language of the transcript, max 90 characters, 1-2 emoji, no hashtags",
 "corecturi": [{"i": word_index, "w": "corrected word"}]}
In "corecturi" fix only clear transcription mistakes (names: {name}, {game}). Don't change the meaning. Can be empty."""
PROMPT_TITLE_EN = ("You write titles for short clips of the streamer {name} ({game}). Write ONE new title, short "
                   "(max 70 characters), funny, in the language of the transcript, with 1 emoji, NO hashtags, different "
                   "from the old title. Reply only JSON: {\"titlu\": \"...\"}")

def _env():
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "")
    if not base and key:
        base = "https://api.openai.com/v1"
    if not model and base:
        model = "gpt-4o-mini"
    return base, key, model


def available():
    base, key, _ = _env()
    return bool(base and (key or "localhost" in base or "127.0.0.1" in base))


def chat(system, user, timeout=90):
    base, key, model = _env()
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    r = requests.post(f"{base}/chat/completions", headers=h, timeout=timeout, json={
        "model": model, "temperature": 0.4,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else {}


def judge(cand, words_rel):
    """cand: detector candidate (times relative to clip window); words_rel: words with clip-relative times.
    Returns dict or None on failure."""
    lines = [f"[{i}] {w['s']:.1f}s {w['w']}" for i, w in enumerate(words_rel)]
    user = (f"Semnale: {', '.join(cand['why'])}; scor euristic {cand['score']}.\n"
            f"Durata ferestrei: {cand['end'] - cand['start']:.0f}s (secundele de mai jos sunt relative la început).\n\n"
            "Cuvinte:\n" + "\n".join(lines[:600]))
    try:
        return chat(texts.fill(PROMPT_JUDGE if texts.is_ro() else PROMPT_JUDGE_EN), user)
    except Exception as e:
        log.warning("LLM indisponibil (%s) -> continui fara", str(e)[:120])
        return None


PROMPT_TITLE = ("Ești editor de TikTok pentru clipurile streamerului {name} ({game}). "
                "Scrie UN titlu NOU, scurt (max 70 caractere), amuzant și viral, în română corectă cu diacritice (ș ț ă â î), "
                "cu 1 emoji, FĂRĂ hashtag-uri, diferit de titlul vechi. Răspunde doar JSON: {\"titlu\": \"...\"}")


def retitle(text, old_title):
    """New viral title for a clip (used by '🔄 Refă textul'). None if the LLM is down."""
    try:
        j = chat(texts.fill(PROMPT_TITLE if texts.is_ro() else PROMPT_TITLE_EN), f"Titlul vechi: {old_title}\nCe se spune în clip: {text[:1500]}", timeout=45)
        t = " ".join(str(j.get("titlu", "")).replace("#", " ").split())
        return t[:90] if t and t != old_title else None
    except Exception as e:
        log.warning("LLM indisponibil pentru titlu (%s)", str(e)[:80])
        return None
