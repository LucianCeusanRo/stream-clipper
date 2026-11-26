"""YouTube Shorts upload with the official YouTube Data API v3 - no extra libraries.

You bring your own OAuth client (Google Cloud Console -> APIs & Services -> Credentials -> "OAuth client ID",
type "Desktop app", YouTube Data API v3 enabled) and point config.yaml at the downloaded JSON:
    youtube_client_secret: "C:/path/client_secret.json"
"Connect" in Accounts opens Google's consent page in your browser; Google redirects back to this app on
127.0.0.1 and the token is saved encrypted (Windows DPAPI) in data/accounts/<id>/youtube_token.json (local only, never in git).
Scope: youtube.upload only (upload videos, nothing else).

Not connected -> export: the clip and a .txt with title + description go to data/exports/<id>/ so you can upload
by hand. Quota note: an upload costs 1600 units; the default project quota (10,000/day) allows ~6 uploads a day.
"""
import json, secrets, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from . import accounts
from . import secretstore
from .util import cfg, load_json, log, save_json

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
_pending = {}                     # state -> (account id, redirect uri, time)


def client():
    """-> (client_id, client_secret) from the JSON Google gives you, or None if not configured."""
    p = str(cfg().get("youtube_client_secret") or "").strip()
    if not p:
        return None
    j = load_json(Path(p), None)
    if not isinstance(j, dict):
        return None
    j = j.get("installed") or j.get("web") or j
    if j.get("client_id") and j.get("client_secret"):
        return j["client_id"], j["client_secret"]
    return None


def _post(url, data, timeout=30):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def auth_url(acc_id, port):
    """Step 1 of connecting: the Google consent page URL (opened in your browser)."""
    cl = client()
    if not cl:
        raise ValueError("lipsește youtube_client_secret în config.yaml (clientul tău OAuth Google, tip Desktop app)")
    state = secrets.token_urlsafe(16)
    redirect = f"http://127.0.0.1:{port}/oauth/youtube"
    _pending[state] = (acc_id, redirect, time.time())
    q = {"client_id": cl[0], "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
         "access_type": "offline", "prompt": "consent", "state": state}
    return AUTH_URL + "?" + urllib.parse.urlencode(q)


def finish_auth(state, code):
    """Step 2: Google sent the browser back with ?code=...; exchange it for tokens and save them locally."""
    acc_id, redirect, t = _pending.pop(state, (None, None, 0))
    if not acc_id or time.time() - t > 900:
        raise ValueError("cerere de conectare expirată sau necunoscută - apasă din nou Conectează")
    cl = client()
    tok = _post(TOKEN_URL, {"code": code, "client_id": cl[0], "client_secret": cl[1], "redirect_uri": redirect,
                            "grant_type": "authorization_code"})
    if not tok.get("refresh_token"):
        raise ValueError("Google nu a trimis refresh_token - încearcă din nou")
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    acc = accounts.get(acc_id)
    f = accounts.token_file(acc)
    f.parent.mkdir(parents=True, exist_ok=True)
    secretstore.save_json(f, tok)            # encrypted with Windows DPAPI
    log.info("YouTube conectat pentru contul %s", acc_id)
    return acc_id


def access_token(acc):
    f = accounts.token_file(acc)
    tok = secretstore.load_json(f, None)
    if not tok:
        return None
    if tok.get("expires_at", 0) > time.time() and tok.get("access_token"):
        return tok["access_token"]
    cl = client()
    if not cl:
        return None
    new = _post(TOKEN_URL, {"client_id": cl[0], "client_secret": cl[1], "refresh_token": tok["refresh_token"],
                            "grant_type": "refresh_token"})
    tok.update(access_token=new["access_token"], expires_at=time.time() + int(new.get("expires_in", 3600)) - 60)
    secretstore.save_json(f, tok)
    return tok["access_token"]


def split_caption(caption):
    """TikTok-style caption -> (title <= 100 chars with #Shorts, description)."""
    words = caption.split()
    text = " ".join(w for w in words if not w.startswith("#")).strip() or "Clip"
    tags = [w for w in words if w.startswith("#")]
    title = text[:90].rstrip()
    if "#shorts" not in title.lower():
        title = (title + " #Shorts")[:100]
    return title, (text + "\n\n" + " ".join(tags + ([] if any(t.lower() == "#shorts" for t in tags) else ["#Shorts"]))).strip()


def export(acc, video: Path, caption: str):
    """Manual-upload export: copy the clip + a text file with title/description."""
    import shutil
    d = accounts.export_dir(acc)
    d.mkdir(parents=True, exist_ok=True)
    dst = d / video.name
    shutil.copyfile(video, dst)
    title, desc = split_caption(caption)
    dst.with_suffix(".txt").write_text(f"TITLE:\n{title}\n\nDESCRIPTION:\n{desc}\n", encoding="utf-8")
    cover = video.with_suffix(".cover.jpg")
    if cover.exists():                                   # the cover you picked (or the auto one) for the manual upload
        shutil.copyfile(cover, dst.with_suffix(".cover.jpg"))
    return str(dst)


def upload(acc, video: Path, caption: str):
    """-> (ok, message, url_or_None, mode). mode = 'api' or 'export'."""
    token = access_token(acc)
    if not token:
        return True, "exportat pentru upload manual", export(acc, video, caption), "export"
    title, desc = split_caption(caption)
    meta = {"snippet": {"title": title, "description": desc, "categoryId": "20"},
            "status": {"privacyStatus": acc.get("visibility", "public"), "selfDeclaredMadeForKids": False}}
    size = video.stat().st_size
    req = urllib.request.Request(UPLOAD_URL, data=json.dumps(meta).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            loc = r.headers.get("Location")
        if not loc:
            return False, "YouTube nu a dat adresa de upload", None, "api"
        with open(video, "rb") as fh:                       # streamed from disk, not loaded into RAM
            put = urllib.request.Request(loc, data=fh, method="PUT",
                                         headers={"Content-Type": "video/mp4", "Content-Length": str(size)})
            with urllib.request.urlopen(put, timeout=1800) as r:
                j = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        if e.code == 403 and "quota" in body.lower():
            return False, "limitare YouTube: cota zilnică API depășită", None, "api"
        return False, f"YouTube API {e.code}: {body}", None, "api"
    vid = j.get("id")
    return (True, "postat", f"https://youtube.com/shorts/{vid}", "api") if vid else (False, "răspuns YouTube fără id", None, "api")
