"""Automated tests (unittest). Run via `python -m streamclip selftest` (isolated temp CLIPPER_HOME)."""
import random, re, json, os, shutil, subprocess, threading, time, unittest, urllib.request, wave
from pathlib import Path
import numpy as np

assert os.environ.get("CLIPPER_HOME"), "run through `python -m streamclip selftest`"
from streamclip import util, db, detect, render, transcribe, texts, pipeline, youtube, app, web, layout, tiktok, viral, effects, jobs  # noqa

QUICK = os.environ.get("CLIPPER_QUICK") == "1"
# the tests use a clipping-campaign style required hashtag; T0 checks the default (none)
util.save_settings({"required_hashtag": "#mycampaign", "streamer_name": "Alex", "game": "GTA 6"})
HAS_FFMPEG = shutil.which("ffmpeg") is not None


def sine_wav(path, secs=120, bursts=(40, 80)):
    sr = 16000; t = np.arange(secs * sr) / sr
    x = 0.02 * np.random.RandomState(0).randn(len(t))
    for b in bursts:                       # loud, bright "screams" with 5 Hz bursts (laugh-like)
        m = (t >= b) & (t < b + 4)
        x[m] += 0.6 * np.sin(2 * np.pi * 1800 * t[m]) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 5 * t[m])))
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())
    return x.astype(np.float32)


def fake_words(secs=120):
    words, sents = [], []
    vocab = ["hai", "frate", "că", "mergem", "acolo", "și", "vedem", "ce", "facem", "acum", "bă", "uite"]
    t = 0.5
    while t < secs - 1:
        w = vocab[int(t * 7) % len(vocab)]
        if 40 <= t < 44 or 80 <= t < 84:
            w = ["doamne", "nu", "se", "poate", "hahaha", "aoleu"][int(t * 3) % 6]
        words.append({"w": w, "s": round(t, 2), "e": round(t + 0.3, 2), "p": 0.9}); t += 0.45
    for i in range(0, len(words), 8):
        g = words[i:i + 8]
        sents.append({"s": g[0]["s"], "e": g[-1]["e"], "t": " ".join(x["w"] for x in g) + "."})
    return words, sents


class T0NoRequiredTag(unittest.TestCase):
    def tearDown(self):
        util.save_settings({"required_hashtag": "#mycampaign"})

    def test_nothing_forced_by_default(self):
        util.save_settings({"required_hashtag": "", "hashtags": ["#gta6"], "extra_hashtags": [], "hashtags_max": 5})
        self.assertEqual(util.cfg()["hashtags"], ["#gta6"])
        cap = pipeline.build_caption("Moment tare 😂")
        self.assertNotIn("#mycampaign", cap); self.assertIn("#gta6", cap)
        self.assertEqual(texts.finalize_caption("a #fyp b"), "a b #fyp")

    def test_titles_use_configured_name(self):
        util.save_settings({"streamer_name": "Maria", "game": "GTA 6"})
        for i in range(30):
            t = texts.new_title("chat", rnd=random.Random(i))
            self.assertNotIn("{", t)
        self.assertIn("MARIA", texts.fill("{NAME} VS CHATUL"))
        util.save_settings({"streamer_name": ""})
        self.assertIn("streamerul", texts.fill("{name}"))
        util.save_settings({"streamer_name": "Alex"})


class T1Config(unittest.TestCase):
    def test_hashtag_forced(self):
        util.save_settings({"hashtags": ["#gta6"]})
        self.assertIn("#mycampaign", util.cfg()["hashtags"])
        self.assertIn("#gta6", util.cfg()["hashtags"])
        util.save_settings({"hashtags": ["#mycampaign"]})

    def test_caption_always_has_tags(self):
        util.save_settings({"hashtags": ["#mycampaign", "#fyp"], "caption_template": "{title}"})
        cap = pipeline.build_caption("Alex a luat-o razna 😂")
        self.assertIn("#mycampaign", cap); self.assertIn("#fyp", cap)
        util.save_settings({"caption_template": "{broken"})
        self.assertIn("#mycampaign", pipeline.build_caption("x"))
        self.assertIn("#mycampaign", web.ensure_tags("am sters hashtag-ul"))
        self.assertEqual(web.ensure_tags("ok #mycampaign #fyp").count("#mycampaign"), 1)
        util.save_settings({"caption_template": "{title} {hashtags}", "hashtags": ["#mycampaign"]})


class T2State(unittest.TestCase):
    def test_gaps_and_dedupe(self):
        v = "vidA"
        db.upsert_video(v, "t", "c", 1000.0, "live")
        db.add_chunk(v, 0, 300, "a", "dvr"); db.add_chunk(v, 600, 900, "b", "live")
        self.assertEqual(db.gaps(v, 0, 900), [[300, 600]])
        db.add_clip(video_id=v, start=100, end=140, score=3, file="f", title="t", caption="c")
        self.assertTrue(db.overlaps_existing(v, 110, 150))
        self.assertFalse(db.overlaps_existing(v, 141, 180))
        self.assertFalse(db.overlaps_existing("other", 110, 150))

    def test_chunk_retry_then_error(self):
        cid = db.add_chunk("vidB", 0, 60, "x", "live")
        db.retry_or_fail(cid, "boom")
        self.assertEqual(db.q("SELECT status FROM chunks WHERE id=?", (cid,), one=True)["status"], "queued")
        db.retry_or_fail(cid, "boom")
        self.assertEqual(db.q("SELECT status FROM chunks WHERE id=?", (cid,), one=True)["status"], "error")

    def test_post_order_manual_first(self):
        a = db.add_clip(video_id="vidC", start=0, end=30, score=9, file="a", title="", caption="")
        b = db.add_clip(video_id="vidC", start=40, end=70, score=1, file="b", title="", caption="")
        self.assertIsNone(db.next_clip_to_post(auto=False))            # manual mode: nothing until approved
        self.assertEqual(db.next_clip_to_post(auto=True)["id"], a)     # auto: best score
        db.x("UPDATE clips SET status='queued', queued_at=? WHERE id=?", (time.time(), b))
        self.assertEqual(db.next_clip_to_post(auto=True)["id"], b)     # approved one goes first
        db.x("UPDATE clips SET status='skipped' WHERE video_id='vidC'")

    def test_crash_recovery(self):
        cid = db.add_chunk("vidD", 0, 60, "x", "live")
        db.x("UPDATE chunks SET status='processing' WHERE id=?", (cid,))
        db._conn.close(); db._conn = None                               # simulate crash + restart
        self.assertEqual(db.q("SELECT status FROM chunks WHERE id=?", (cid,), one=True)["status"], "queued")
        db.x("UPDATE chunks SET status='done' WHERE id=?", (cid,))


class T2bOrphans(unittest.TestCase):
    def test_stale_children_killed_after_crash(self):
        import sys
        code = "import subprocess,sys,os; sys.path.insert(0, os.getcwd()); from streamclip import util; " \
               "util.spawn([sys.executable, '-c', 'import time; time.sleep(120)  # yt_dlp']); os._exit(0)"
        subprocess.run([sys.executable, "-c", code], check=True, cwd=os.getcwd())
        pids = json.loads(util.PIDS.read_text())
        self.assertTrue(pids)
        util.kill_stale_children()
        time.sleep(1)
        for pid in pids:
            if sys.platform != "win32":
                self.assertFalse(Path(f"/proc/{pid}").exists() and "yt_dlp" in Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="ignore"))


class T3Romanian(unittest.TestCase):
    def test_clitics_any_gap_and_non_latin(self):
        from streamclip.transcribe import merge_clitics, clean_word
        W = lambda t, a, b: {"w": t, "s": a, "e": b}
        got = [w["w"] for w in merge_clitics([W("V", 0, .2), W("-am", 1.5, 1.8), W("gata.", 2, 2.2), W("-a", 3, 3.1)])]
        self.assertEqual(got, ["V-am", "gata.", "a"])
        self.assertEqual(clean_word(".อะไร"), "")
        from streamclip.transcribe import restore_diacritics as rd
        self.assertEqual(" ".join(rd(x) for x in "Pana si sa faca, bai! Daca-i".split()), "Până și să facă, băi! Dacă-i")
        self.assertEqual(rd("casa"), "casa")
        self.assertEqual(clean_word("Țeapă!"), "Țeapă!")

    def test_diacritics(self):
        self.assertEqual(transcribe.fix_ro("şi ţară Ş Ţ ã"), "și țară Ș Ț ă")
        self.assertEqual("ș ț ă î â".upper(), "Ș Ț Ă Î Â")

    def test_clitics_and_loops(self):
        w = [{"w": "s", "s": 0, "e": .2}, {"w": "-a", "s": .2, "e": .4}, {"w": "dus", "s": .5, "e": .8}]
        self.assertEqual([x["w"] for x in transcribe.merge_clitics(w)], ["s-a", "dus"])
        s = [{"s": i, "e": i + 1, "t": "Nu știu ce văd"} for i in range(5)]
        self.assertEqual(len(transcribe.dedupe_loops(s)), 2)

    def test_hallucination_filter(self):
        self.assertFalse(transcribe.keep_word("surprisingly", 0.1))
        self.assertTrue(transcribe.keep_word("frate", 0.1))
        self.assertTrue(transcribe.keep_word("anything", 0.9))

    def test_keywords(self):
        s, cats = detect._kw_score("Doamne, nu se poate! hahaha")
        self.assertGreater(s, 2); self.assertIn("ras", cats); self.assertIn("exclamatie", cats)

    def test_ass_has_diacritics_and_masks(self):
        util.save_settings({"censor_swears": True})
        ass = render.build_ass([{"w": "Ce", "s": 0.1, "e": 0.3}, {"w": "pula", "s": 0.3, "e": 0.6},
                                {"w": "știi", "s": 0.7, "e": 1.0}, {"w": "țară", "s": 1.1, "e": 1.4}], 5, "ALEX A ÎNNEBUNIT 😂", "split")
        self.assertIn("ȘTII", ass); self.assertIn("ȚARĂ", ass); self.assertIn("ALEX A ÎNNEBUNIT", ass)
        self.assertNotIn("PULA", ass); self.assertIn("P***", ass); self.assertNotIn("😂", ass)


class T4Detect(unittest.TestCase):
    def test_finds_moments_in_limits(self):
        pcm = sine_wav(Path(util.DATA) / "t.wav")
        words, sents = fake_words()
        c = dict(util.cfg())
        cands = detect.find_moments(pcm, words, sents, None, 0, c)
        self.assertTrue(cands, "no moments found")
        for x in cands:
            self.assertGreaterEqual(x["end"] - x["start"], c["clip_min_sec"] - 0.01)
            self.assertLessEqual(x["end"] - x["start"], c["clip_max_sec"] + 0.01)
        peaks = sorted(x["peak"] for x in cands)
        self.assertTrue(any(35 <= p <= 50 for p in peaks) or any(75 <= p <= 90 for p in peaks), peaks)
        # non overlapping
        cs = sorted(cands, key=lambda x: x["start"])
        for a, b in zip(cs, cs[1:]):
            self.assertLessEqual(a["end"], b["start"])

    def test_preroll_excluded(self):
        pcm = sine_wav(Path(util.DATA) / "t2.wav", bursts=(10,))
        words, sents = fake_words()
        cands = detect.find_moments(pcm, words, sents, None, 60, dict(util.cfg()))
        self.assertTrue(all(x["peak"] >= 60 for x in cands))

    def test_chat_parse(self):
        d = Path(util.DATA) / "chatvid"; d.mkdir(exist_ok=True)
        lines = [json.dumps({"replayChatItemAction": {"actions": [{"x": "hahaha"}], "videoOffsetTimeMsec": str(ms)}})
                 for ms in (1000, 1500, 2100, 5000)]
        (d / "chat.live_chat.json").write_text("\n".join(lines), encoding="utf-8")
        c = youtube.chat_counts(d, None, 0, 10)
        self.assertEqual(c[1], 4); self.assertEqual(c[2], 2)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg lipseste")
class T5Render(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path(util.DATA) / "synthetic.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=30",
                        "-f", "lavfi", "-i", "sine=f=440:d=30", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "aac", str(cls.src)], check=True)

    def _check(self, out):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "json", str(out)], capture_output=True, text=True)
        s = json.loads(r.stdout)["streams"][0]
        self.assertEqual((s["width"], s["height"]), (1080, 1920))
        self.assertAlmostEqual(util.ffprobe_duration(out), 21, delta=1.0)

    def test_split_and_blur(self):
        words = [{"w": w, "s": i * 0.5, "e": i * 0.5 + 0.4} for i, w in enumerate("Ce faci frate știi țară îți".split())]
        for lay in (["split"] if QUICK else ["split", "blur", "fill"]):
            out = Path(util.DATA) / f"r_{lay}.mp4"
            render.render(str(self.src), 2, 23, words, "HOOK DE TEST ȘȚĂ", out, lay, None)
            self._check(out)

    def test_stable_face_picks_the_static_one(self):
        from streamclip import facecam
        cam = [10, 100, 60, 60, 0.9]                                  # webcam face: same place every frame
        dets = [[cam, [300 + 40 * i, 200, 50, 50, 0.8]] for i in range(8)]   # in-game face moves
        face, hits = facecam.stable_face(dets, 8)
        self.assertEqual(hits, 8); self.assertAlmostEqual(face[0], 10, delta=1)
        box = facecam.face_box(face, 960, 540)
        self.assertTrue(all(0 <= v <= 1 for v in box)); self.assertLessEqual(box[0] + box[2], 1.0001)
        self.assertEqual(facecam.stable_face([[], []], 2), (None, 0))

    def test_layout_no_face_falls_back_to_blur(self):
        lay, box = layout.decide(str(self.src), 0, 20)
        self.assertEqual(lay, "blur")


class T6AppAndPosting(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def fake_upload(path, caption, visibility=None):
            self.calls.append(caption)
            return self.result
        self._orig = tiktok.upload
        tiktok.upload = fake_upload
        util.save_settings({"manual_min_gap_minutes": 0})

    def tearDown(self):
        tiktok.upload = self._orig

    def _clip(self, status="queued"):
        f = Path(util.DATA) / f"c{time.time_ns()}.mp4"; f.write_bytes(b"x")
        cid = db.add_clip(video_id="vidP", start=time.time() % 1000, end=time.time() % 1000 + 30, score=5, file=str(f),
                          title="t", caption="t #mycampaign", status=status)
        db.x("UPDATE clips SET queued_at=? WHERE id=?", (time.time(), cid))
        return cid

    def test_post_ok(self):
        self.result = (True, "postat", "https://www.tiktok.com/@x/video/1")
        cid = self._clip()
        self.assertTrue(app.post_one(db.q("SELECT * FROM clips WHERE id=?", (cid,), one=True)))
        r = db.q("SELECT * FROM clips WHERE id=?", (cid,), one=True)
        self.assertEqual(r["status"], "posted"); self.assertTrue(r["url"]); self.assertIn("#mycampaign", self.calls[0])

    def test_post_fail_retry_then_failed(self):
        self.result = (False, "timeout: retea", None)
        cid = self._clip()
        for _ in range(3):
            app.post_one(db.q("SELECT * FROM clips WHERE id=?", (cid,), one=True))
        self.assertEqual(db.q("SELECT status FROM clips WHERE id=?", (cid,), one=True)["status"], "failed")

    def test_unconfirmed_never_reposted(self):
        self.result = (False, "nu am primit confirmarea", None)
        cid = self._clip()
        app.post_one(db.q("SELECT * FROM clips WHERE id=?", (cid,), one=True))
        self.assertEqual(db.q("SELECT status FROM clips WHERE id=?", (cid,), one=True)["status"], "unconfirmed")
        self.assertNotEqual((db.next_clip_to_post(auto=True) or {"id": None})["id"], cid)

    def test_daily_cap_and_pause(self):
        self.result = (True, "postat", None)
        util.save_settings({"daily_post_cap": 1, "auto_post": False})
        db.x("UPDATE clips SET status='skipped' WHERE status IN ('queued','pending')")
        db.x("UPDATE clips SET posted_at=0 WHERE status IN ('posted','unconfirmed')")   # earlier tests = not today
        a, b = self._clip(), self._clip()
        th = threading.Thread(target=app.poster, daemon=True); th.start()
        t_end = time.time() + 20
        while time.time() < t_end and len(self.calls) < 1:
            time.sleep(0.2)
        time.sleep(2)
        self.assertEqual(len(self.calls), 1, "cap 1/zi trebuia respectat")
        self.assertIn("limita", app.STATUS["poster"])
        app.STOP.set(); th.join(10); app.STOP.clear()
        util.save_settings({"daily_post_cap": 30})


class T6bLLM(unittest.TestCase):
    def test_judge_with_mock_openai_server(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from streamclip import llm
        reply = {"scor": 8, "categorie": "amuzant", "start": 1, "end": 25, "hook": "ALEX A ÎNNEBUNIT",
                 "titlu": "Alex și trotineta 😂", "corecturi": [{"i": 0, "w": "știi"}]}

        class M(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert body["messages"][0]["content"].startswith("Ești editorul")
                out = json.dumps({"choices": [{"message": {"content": "```json\n" + json.dumps(reply, ensure_ascii=False) + "\n```"}}]}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), M)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ.update(LLM_BASE_URL=f"http://127.0.0.1:{srv.server_port}/v1", LLM_API_KEY="x", LLM_MODEL="m")
        try:
            self.assertTrue(llm.available())
            words = [{"w": "stii", "s": 0.5, "e": 0.8}, {"w": "frate", "s": 1, "e": 1.3}]
            j = llm.judge({"why": ["ras"], "score": 2, "start": 0, "end": 30}, words)
            self.assertEqual(j["scor"], 8)
            pipeline.apply_corrections(words, j["corecturi"])
            self.assertEqual(words[0]["w"], "știi")
        finally:
            srv.shutdown()
            for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
                os.environ.pop(k, None)

    def test_llm_down_returns_none(self):
        from streamclip import llm
        os.environ.update(LLM_BASE_URL="http://127.0.0.1:9/v1", LLM_API_KEY="x")
        try:
            self.assertIsNone(llm.judge({"why": [], "score": 1, "start": 0, "end": 30}, []))
        finally:
            os.environ.pop("LLM_BASE_URL"); os.environ.pop("LLM_API_KEY")


class T7Web(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 18000 + os.getpid() % 1000
        cls.srv = web.serve(cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def req(self, path, body=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_dashboard(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=10) as r:
            self.assertIn("Stream", r.read().decode("utf-8"))
        code, st = self.req("/api/state"); self.assertEqual(code, 200); self.assertIn("watching", st)
        cid = db.add_clip(video_id="vidW", start=1, end=30, score=4, file=str(Path(util.DATA) / "w.mp4"), title="t", caption="t")
        code, lst = self.req("/api/clips?status=pending"); self.assertTrue(any(x["id"] == cid for x in lst))
        code, _ = self.req("/api/clip", {"id": cid, "action": "post", "caption": "fara hashtag"})
        r = db.q("SELECT * FROM clips WHERE id=?", (cid,), one=True)
        self.assertEqual(r["status"], "queued"); self.assertIn("#mycampaign", r["caption"])
        code, _ = self.req("/api/clip", {"id": cid, "action": "delete"})
        self.assertEqual(db.q("SELECT status FROM clips WHERE id=?", (cid,), one=True)["status"], "deleted")
        code, _ = self.req("/api/clip", {"id": cid, "action": "post"}); self.assertEqual(code, 400)   # deleted can't be posted
        c2 = db.add_clip(video_id="vidW", start=40, end=70, score=3, file=str(Path(util.DATA) / "w2.mp4"), title="t", caption="t")
        self.req("/api/clip", {"id": c2, "action": "skip"})
        code, lst = self.req("/api/clips?status=all")
        ids = [x["id"] for x in lst]; self.assertIn(c2, ids); self.assertNotIn(cid, ids)   # gallery = all but deleted
        code, r = self.req("/api/settings", {"hashtags": "#gta6 #alex", "daily_post_cap": 40})
        self.assertEqual(code, 200); self.assertIn("#mycampaign", r["hashtags"])
        code, _ = self.req("/api/settings", {"post_interval_min_minutes": 0}); self.assertEqual(code, 400)
        code, _ = self.req("/api/control", {"action": "stop"}); self.assertFalse(app.WATCHING.is_set())
        self.req("/api/control", {"action": "start"}); self.assertTrue(app.WATCHING.is_set())
        code, _ = self.req("/api/clip", {"id": 999999, "action": "post"}); self.assertEqual(code, 404)


def first_tag(cap):
    tags = re.findall(r"(?<![\w#])#\w+", cap)
    return tags[0] if tags else None


class T8HashtagsFirst(unittest.TestCase):
    def tearDown(self):
        util.save_settings({"hashtags": ["#mycampaign"], "extra_hashtags": [], "hashtags_max": 5,
                            "caption_template": "{title} {hashtags}"})

    def test_required_tag_always_first(self):
        # user puts it last / forgets it / template puts hashtags first: it's still the FIRST hashtag
        util.save_settings({"hashtags": ["#gta6", "#fyp", "#MYCAMPAIGN"], "extra_hashtags": ["#viral", "#romania"],
                            "hashtags_max": 5})
        self.assertEqual(util.cfg()["hashtags"][0], "#mycampaign")
        for tpl in ("{title} {hashtags}", "{hashtags} {title}", "{title}", "#fyp {title} {hashtags} #extra"):
            util.save_settings({"caption_template": tpl})
            for i in range(20):
                cap = pipeline.build_caption("Alex a luat-o razna 😂 #gta6", random.Random(i))
                self.assertEqual(first_tag(cap), "#mycampaign", cap)
                self.assertEqual(cap.lower().count("#mycampaign"), 1, cap)
        util.save_settings({"caption_template": "{title} {hashtags}"})
        cap = pipeline.build_caption("x", random.Random(3))
        self.assertLessEqual(len(re.findall(r"#\w+", cap)), 5)
        self.assertEqual(first_tag(web.ensure_tags("#fyp #viral textul meu")), "#mycampaign")
        self.assertEqual(first_tag(web.ensure_tags("fara nimic")), "#mycampaign")
        self.assertEqual(texts.finalize_caption("a #fyp b #mycampaign"), "a b #mycampaign #fyp")

    def test_upload_gets_required_tag_first(self):
        got = {}
        orig = tiktok._upload
        tiktok._upload = lambda v, cap, vis=None: (got.setdefault("cap", cap), (False, "test"))[1]
        try:
            tiktok.upload(Path("x.mp4"), "titlu #fyp #gta6")
        finally:
            tiktok._upload = orig
        self.assertEqual(first_tag(got["cap"]), "#mycampaign")

    def test_retext_new_variant_each_press(self):
        util.save_settings({"hashtags": ["#mycampaign", "#alex"], "extra_hashtags": ["#fyp", "#viral", "#romania", "#funny"],
                            "hashtags_max": 4, "use_llm": False})
        f = Path(util.DATA) / "rt.mp4"; f.write_bytes(b"x")
        cid = db.add_clip(video_id="vidT", start=5000, end=5030, score=3, file=str(f), title="Alex vs chat, runda 1 🥊",
                          caption="x", cat="chat", text="bla")
        seen = set()
        prev = "Alex vs chat, runda 1 🥊"
        for i in range(6):
            r = pipeline.retext(cid, random.Random(i))
            self.assertNotEqual(r["title"], prev); prev = r["title"]
            self.assertEqual(first_tag(r["caption"]), "#mycampaign", r["caption"])
            self.assertIn("#alex ", r["caption"] + " ")
            self.assertLessEqual(len(re.findall(r"#\w+", r["caption"])), 4)
            seen.add(r["caption"])
        self.assertGreaterEqual(len(seen), 4)
        db.x("UPDATE clips SET status='posted' WHERE id=?", (cid,))
        with self.assertRaises(pipeline.ClipError):
            pipeline.retext(cid)
        util.save_settings({"use_llm": True})


class T9Viral(unittest.TestCase):
    def test_score_range_and_factors(self):
        lo, f1 = viral.compute({"loud": 0, "laugh": 0, "chat_z": 0, "nkw": 0}, 58)
        hi, f2 = viral.compute({"loud": 4, "laugh": 3, "chat_z": 4, "nkw": 4}, 28, True, "ras", 4)
        self.assertTrue(5 <= lo < 40 < 80 <= hi <= 95, (lo, hi))
        self.assertEqual(set(f2), {"hook", "emotie", "cuvinte", "chat", "durata"})
        nochat, f3 = viral.compute({"loud": 4, "laugh": 3, "chat_z": None, "nkw": 4}, 28, True, "ras", 4)
        self.assertNotIn("chat", f3); self.assertGreater(nochat, 80)
        withai, f4 = viral.compute({"loud": 1, "laugh": 0, "chat_z": None, "nkw": 1}, 30, llm_score=10)
        self.assertIn("ai", f4)
        self.assertIn("Hook", viral.tooltip(f2))
        r = web.clip_row({"id": 1, "file": "a.mp4", "start": 0, "end": 30, "score": 3, "viral": None, "factors": None, "src": None})
        self.assertTrue(5 <= r["viral"] <= 95); self.assertFalse(r["can_recut"])


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg lipseste")
class T10Recut(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path(util.DATA) / "recut_src.mp4"; cls.src.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=60",
                        "-f", "lavfi", "-i", "sine=f=440:d=60", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "aac", str(cls.src)], check=True)

    def _clip(self):
        out = Path(util.DATA) / "clips" / f"vidR_{time.time_ns()}.mp4"; out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"old")
        words = [{"w": f"cuvânt{i}", "s": i * 1.0, "e": i * 1.0 + 0.6} for i in range(60)]
        sents = [{"s": float(a), "e": float(a + 4.6), "t": "propoziție"} for a in range(0, 60, 5)]
        meta = {"start": 1012, "end": 1042, "layout": "blur", "cam_box": None, "cat": "chat", "words": [],
                "feat": {"loud": 2, "laugh": 0, "chat_z": None, "nkw": 1}, "llm": None,
                "src_abs0": 1000.0, "src_s": 12.0, "src_e": 42.0, "src_dur": 60.0, "src_words": words, "src_sents": sents}
        util.save_json(out.with_suffix(".json"), meta)
        return db.add_clip(video_id="vidR", start=1012, end=1042, score=2, file=str(out), title="t", caption="t #mycampaign",
                           hook="TEST ȘȚ", layout="blur", cat="chat", src=str(self.src)), out

    def test_manual_trim_and_snap(self):
        cid, old = self._clip()
        r = pipeline.recut(cid, dstart=-2, dend=3, snap=False)
        row = db.q("SELECT * FROM clips WHERE id=?", (cid,), one=True)
        self.assertAlmostEqual(row["start"], 1010.0, places=1); self.assertAlmostEqual(row["end"], 1045.0, places=1)
        self.assertAlmostEqual(util.ffprobe_duration(row["file"]), 35.0, delta=0.6)
        self.assertFalse(old.exists()); self.assertTrue(Path(row["file"]).exists()); self.assertEqual(row["version"], 2)
        # snapping: start 10+1.3=11.3 -> sentence start 10 (-0.1); end 45+1.2=46.2 -> sentence end 44.6 (+0.35)
        pipeline.recut(cid, dstart=1.3, dend=1.2, snap=True)
        row = db.q("SELECT * FROM clips WHERE id=?", (cid,), one=True)
        self.assertAlmostEqual(row["start"] - 1000, 9.9, places=1); self.assertAlmostEqual(row["end"] - 1000, 44.95, places=1)
        m = util.load_json(Path(row["file"]).with_suffix(".json"))
        self.assertTrue(m["words"] and m["words"][0]["s"] >= 0)
        with self.assertRaises(pipeline.ClipError):
            pipeline.recut(cid, dstart=30, dend=-30, snap=False)       # too short

    def test_missing_source_and_web(self):
        cid, _ = self._clip()
        db.x("UPDATE clips SET src=NULL WHERE id=?", (cid,))
        with self.assertRaises(pipeline.ClipError):
            pipeline.recut(cid)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg lipseste")
class T11Effects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path(util.DATA) / "fx_src.mp4"; cls.src.parent.mkdir(parents=True, exist_ok=True)
        # quiet tone with two loud bursts (= "screams") at 6 s and 14 s
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=20", "-f", "lavfi",
                        "-i", "aevalsrc='0.03*sin(2*PI*300*t)+0.9*sin(2*PI*900*t)*(between(t,6,6.8)+between(t,14,14.8))':s=48000:d=20",
                        "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(cls.src)], check=True)

    def words(self):
        ws = "hai că râde haha băi ce prost doamne nu se poate frate gata".split()
        return [{"w": w, "s": 1 + i * 1.4, "e": 1 + i * 1.4 + 0.5} for i, w in enumerate(ws)]

    def test_plan(self):
        p = effects.plan(self.src, 0, 20, self.words(), dict(effects.DEFAULTS))
        self.assertTrue(any(abs(t - 6) < 0.6 for t in p["punch"]), p["punch"])
        self.assertTrue(any(abs(t - 14) < 0.6 for t in p["punch"]), p["punch"])
        self.assertTrue(p["emojis"] and all((effects.ASSETS / "emoji" / f"{e['code']}.png").exists() for e in p["emojis"]))
        self.assertTrue(p["rage"]); self.assertLessEqual(len(p["sfx"]), 2); self.assertTrue(p["boost"])
        off = effects.plan(self.src, 0, 20, self.words(), {k: (False if isinstance(v, bool) else v) for k, v in effects.DEFAULTS.items()})
        self.assertFalse(off["punch"] or off["emojis"] or off["sfx"] or off["boost"] or off["rage"])
        for f in ("boom.wav", "whoosh.wav", "pop.wav"):
            self.assertTrue((effects.ASSETS / "sfx" / f).exists())

    def test_render_with_all_effects_and_loudness(self):
        util.save_settings({"effects": dict(effects.DEFAULTS, progress_bar=True)})
        out = Path(util.DATA) / "fx_out.mp4"
        render.render(self.src, 0, 20, self.words(), "TEST EFECTE ȘȚ", out, "blur")
        self.assertAlmostEqual(util.ffprobe_duration(out), 20, delta=0.5)
        i, peak = render.measure_lufs(out)
        self.assertAlmostEqual(i, -14, delta=1.5); self.assertLessEqual(peak, -0.5)
        ass = out.with_suffix(".ass").read_text(encoding="utf-8")
        self.assertIn("\\fscx130", ass)                     # word bounce
        self.assertIn("&H003B3BFF&", ass)                   # keyword colour (rage = red)
        util.save_settings({"effects": {k: (False if isinstance(v, bool) else v) for k, v in effects.DEFAULTS.items()}})
        render.render(self.src, 0, 10, self.words(), "", out, "blur")    # all effects off still renders
        self.assertAlmostEqual(util.ffprobe_duration(out), 10, delta=0.5)
        util.save_settings({"effects": dict(effects.DEFAULTS)})


class T12Jobs(unittest.TestCase):
    def test_validation_and_local_file_job(self):
        self.assertEqual(jobs.parse_time("1:02:03"), 3723); self.assertEqual(jobs.parse_time("90"), 90)
        self.assertIsNone(jobs.parse_time(""))
        with self.assertRaises(ValueError):
            jobs.parse_time("abc")
        with self.assertRaises(ValueError):
            jobs.submit("nu e link")
        with self.assertRaises(ValueError):
            jobs.submit("https://youtu.be/x", "1:00", "1:10")
        if not HAS_FFMPEG:
            return
        src = Path(util.DATA) / "job_src.mp4"; src.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=70", "-f", "lavfi",
                        "-i", "sine=f=300:d=70", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
        calls = []

        def fake_process(ch, over=None):            # no Whisper in tests: create 2 fake clips per part
            calls.append((ch["t0"], ch["t1"], over))
            for k in range(2):
                f = Path(util.DATA) / f"jobclip_{ch['id']}_{k}.mp4"; f.write_bytes(b"x")
                db.add_clip(video_id=ch["video_id"], start=ch["t0"] + k * 25, end=ch["t0"] + k * 25 + 20, score=1 + k,
                            file=str(f), title="t", caption="t #mycampaign", viral=40 + 10 * k + len(calls))
            return 2
        orig = pipeline.process_chunk; pipeline.process_chunk = fake_process
        util.save_settings({"chunk_minutes": 0.5})
        try:
            j = jobs.submit(str(src), "0:05", "1:05", 3)
            t_end = time.time() + 60
            while time.time() < t_end and jobs.JOBS[j["id"]]["status"] not in ("gata", "eroare"):
                time.sleep(0.3)
            jj = jobs.JOBS[j["id"]]
            self.assertEqual(jj["status"], "gata", jj); self.assertEqual(jj["progress"], 100)
            self.assertEqual(len(calls), 2); self.assertAlmostEqual(calls[0][0], 5, delta=0.1)
            left = db.q("SELECT * FROM clips WHERE video_id=? AND status='pending'", ("job-" + j["id"],))
            self.assertEqual(len(left), 3)                         # only the best 3 are kept
        finally:
            pipeline.process_chunk = orig
            util.save_settings({"chunk_minutes": 5})


if __name__ == "__main__":
    unittest.main()
