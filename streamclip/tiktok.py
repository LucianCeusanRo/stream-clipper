"""Post clips to TikTok through the normal website (TikTok Studio upload page) with Playwright.

The browser profile is persistent (data/tiktok_profile): you log in ONCE with `login_tiktok.bat`,
then every upload reuses that session - no passwords stored by this program.
Flow and selectors follow the open-source tiktok-uploader project (wkaisertexas/tiktok-uploader, MIT),
updated for the TikTok Studio page, with screenshots on every failure in data/screens/.
"""
import re, time
from pathlib import Path
from .util import DATA, cfg, log

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=webapp&lang=ro-RO"
PROFILE = DATA / "tiktok_profile"
SHOTS = DATA / "screens"


def _ctx(p, headless=None):
    c = cfg()
    args = dict(user_data_dir=str(PROFILE), headless=c.get("headless", False) if headless is None else headless,
                viewport={"width": 1280, "height": 900}, locale="ro-RO",
                args=["--disable-blink-features=AutomationControlled"])
    ch = c.get("browser_channel", "chrome")
    if ch and ch != "chromium":
        args["channel"] = ch
    try:
        return p.chromium.launch_persistent_context(**args)
    except Exception as e:
        if "channel" in args:
            log.warning("nu pot porni %s (%s), folosesc Chromium inclus", ch, str(e)[:80])
            args.pop("channel")
            return p.chromium.launch_persistent_context(**args)
        raise


_lock = __import__("threading").Lock()     # one browser at a time (login / upload)
LOGIN_STATE = {"state": "necunoscut"}


def login(timeout=600):
    """Opens a visible browser on TikTok login; you log in by hand; we wait until the session cookie appears
    (max 10 min) and keep it in the persistent profile. No password is stored by this program."""
    from playwright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True)
    with _lock, sync_playwright() as p:
        ctx = _ctx(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.tiktok.com/login")
        LOGIN_STATE["state"] = "astept sa te loghezi in fereastra Chrome"
        print(">>> Logheaza-te pe contul de TikTok in fereastra deschisa. Se salveaza automat.")
        ok = False
        t_end = time.time() + timeout
        while time.time() < t_end:
            try:
                if any(ck["name"] == "sessionid" and ck["value"] for ck in ctx.cookies("https://www.tiktok.com")):
                    ok = True
                    page.wait_for_timeout(4000)
                    break
                page.wait_for_timeout(2000)
            except Exception:
                break        # window closed by the user
        try:
            ctx.close()
        except Exception:
            pass
    LOGIN_STATE["state"] = "logat" if ok else "nelogat"
    print("Logare salvata!" if ok else "ATENTIE: nu vad sesiunea TikTok. Mai incearca o data.")
    return ok


def is_logged_in():
    """Cheap check: does the saved profile hold a TikTok session cookie? (reads the browser profile offline)"""
    from playwright.sync_api import sync_playwright
    if not PROFILE.exists():
        return False
    if not _lock.acquire(timeout=1):
        return None   # busy uploading
    try:
        with sync_playwright() as p:
            ctx = _ctx(p, headless=True)
            ok = any(ck["name"] == "sessionid" and ck["value"] for ck in ctx.cookies("https://www.tiktok.com"))
            ctx.close()
            return ok
    except Exception:
        return None
    finally:
        _lock.release()


def _shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(SHOTS / f"{int(time.time())}_{name}.png"), full_page=True)
    except Exception:
        pass


def _dismiss(page):
    for sel in ["button:has-text('Not now')", "button:has-text('Acum nu')", "button:has-text('Got it')",
                "button:has-text('Am înțeles')", "button:has-text('Accept all')", "button:has-text('Acceptă tot')",
                "div[role='dialog'] button[aria-label='Close']"]:
        try:
            b = page.locator(sel).first
            if b.is_visible(timeout=300):
                b.click(timeout=1000)
        except Exception:
            pass


def upload(video: Path, caption: str, visibility=None):
    """Upload one video. Returns (ok, message, url_or_None)."""
    from .texts import finalize_caption
    caption = finalize_caption(caption)        # last safety net: required_hashtag first, if set
    with _lock:
        ok, msg = _upload(video, caption, visibility)
        url = None
        if ok:
            url = latest_video_url()
        return ok, msg, url


def latest_video_url():
    """Best effort: link of the newest post from TikTok Studio's content list."""
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            ctx = _ctx(p)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://www.tiktok.com/tiktokstudio/content", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)
            href = page.evaluate("() => { const a = [...document.querySelectorAll('a[href*=\"/video/\"]')]; return a.length ? a[0].href : null }")
            ctx.close()
            return href
    except Exception:
        return None


def _upload(video: Path, caption: str, visibility=None):
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    visibility = visibility or cfg().get("visibility", "public")
    with sync_playwright() as p:
        ctx = _ctx(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            if "login" in page.url:
                _shot(page, "not_logged_in")
                return False, "nu esti logat pe TikTok: ruleaza login_tiktok.bat"
            _dismiss(page)
            frame = page
            if page.locator("iframe").count() and not page.locator("input[type=file]").count():
                frame = page.frame_locator("iframe").first
            frame.locator("input[type=file]").first.set_input_files(str(video), timeout=60000)
            # caption editor (Draft.js contenteditable)
            ed = frame.locator("div[contenteditable='true']").first
            ed.wait_for(state="visible", timeout=120000)
            page.wait_for_timeout(2500)
            ed.click()
            page.keyboard.press("Control+A"); page.keyboard.press("Delete")
            for part in caption.split(" "):
                if part.startswith("#"):
                    page.keyboard.type(part, delay=60)
                    page.wait_for_timeout(1800)          # hashtag suggestion popup
                    page.keyboard.type(" ", delay=30)
                else:
                    page.keyboard.type(part + " ", delay=25)
            page.wait_for_timeout(800)
            if visibility != "public":
                try:
                    frame.get_by_text(re.compile("Everyone|Toată lumea|Oricine")).first.click(timeout=3000)
                    frame.get_by_text(re.compile("Only you|Doar tu|Numai tu")).first.click(timeout=3000)
                except Exception:
                    log.warning("nu am putut seta vizibilitatea; ramane setarea implicita")
            # wait for upload/processing to finish: Post button enabled
            post = frame.locator("button[data-e2e='post_video_button']").first
            t_end = time.time() + 600
            while time.time() < t_end:
                try:
                    if post.is_visible() and post.is_enabled() and post.get_attribute("aria-disabled") != "true" \
                            and post.get_attribute("data-disabled") != "true":
                        break
                except Exception:
                    pass
                page.wait_for_timeout(2000)
            else:
                _shot(page, "post_button_timeout")
                return False, "upload-ul nu s-a terminat in 10 minute"
            _dismiss(page)
            post.click()
            # optional "Post now" confirm (copyright check dialog)
            for sel in ["button:has-text('Post now')", "button:has-text('Postează acum')"]:
                try:
                    page.locator(sel).first.click(timeout=4000)
                except Exception:
                    pass
            ok = False
            t_end = time.time() + 120
            while time.time() < t_end:
                txt = ""
                try:
                    txt = page.inner_text("body", timeout=2000)
                except Exception:
                    pass
                if "tiktokstudio/content" in page.url or any(s in txt for s in (
                        "Your video has been uploaded", "Video published", "Videoclipul a fost publicat",
                        "videoclipul tău a fost încărcat", "Manage your posts", "Gestionează postările")):
                    ok = True
                    break
                page.wait_for_timeout(2000)
            _shot(page, "posted" if ok else "post_unconfirmed")
            return ok, "postat" if ok else "nu am primit confirmarea (verifica in TikTok Studio)"
        except PWTimeout as e:
            _shot(page, "timeout")
            return False, f"timeout: {str(e)[:150]}"
        except Exception as e:
            _shot(page, "error")
            return False, f"eroare: {str(e)[:200]}"
        finally:
            ctx.close()
