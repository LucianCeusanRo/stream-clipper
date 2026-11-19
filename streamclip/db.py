"""Persistent state (SQLite) so nothing is processed or posted twice, even across restarts.

Tables
  videos  : every live/VOD seen (id, title, start timestamp, status)
  chunks  : stream-time ranges [t0, t1) of a video that were downloaded / processed
  clips   : every rendered clip (video_id, start, end in stream time, score, file, caption, posted state)
"""
import sqlite3, threading, time
from .util import DATA

_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (id TEXT PRIMARY KEY, title TEXT, channel TEXT, start_ts REAL,
    status TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, t0 REAL, t1 REAL,
    path TEXT, kind TEXT, status TEXT, created REAL, error TEXT);
CREATE INDEX IF NOT EXISTS ix_chunks_v ON chunks(video_id, t0);
CREATE TABLE IF NOT EXISTS clips (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, start REAL, end REAL,
    score REAL, file TEXT, title TEXT, caption TEXT, text TEXT, why TEXT, status TEXT, created REAL,
    posted_at REAL, attempts INTEGER DEFAULT 0, error TEXT);
CREATE INDEX IF NOT EXISTS ix_clips_v ON clips(video_id, start);
"""


def conn():
    global _conn
    with _lock:
        if _conn is None:
            DATA.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(DATA / "state.db", check_same_thread=False, timeout=30)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            for tbl, col, typ in (("chunks", "tries", "INTEGER DEFAULT 0"), ("clips", "thumb", "TEXT"),
                                  ("clips", "url", "TEXT"), ("clips", "hook", "TEXT"), ("clips", "layout", "TEXT"), ("clips", "queued_at", "REAL"),
                                  ("clips", "viral", "INTEGER"), ("clips", "factors", "TEXT"), ("clips", "cat", "TEXT"),
                                  ("clips", "src", "TEXT"), ("clips", "version", "INTEGER DEFAULT 1")):
                try:
                    _conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError:
                    pass       # column already exists
            _conn.execute("PRAGMA journal_mode=WAL")
            # chunks left half-done by a crash go back into the queue
            _conn.execute("UPDATE chunks SET status='queued' WHERE status='processing'")
            _conn.execute("UPDATE clips SET status='queued' WHERE status='posting'")
            _conn.commit()
        return _conn


def q(sql, args=(), one=False):
    with _lock:
        cur = conn().execute(sql, args)
        rows = cur.fetchall()
        conn().commit()
        return (rows[0] if rows else None) if one else rows


def x(sql, args=()):
    with _lock:
        cur = conn().execute(sql, args)
        conn().commit()
        return cur.lastrowid


# ---- videos ----
def upsert_video(vid, title, channel, start_ts, status):
    x("""INSERT INTO videos(id,title,channel,start_ts,status,updated) VALUES(?,?,?,?,?,?)
         ON CONFLICT(id) DO UPDATE SET title=excluded.title, status=excluded.status,
         start_ts=COALESCE(videos.start_ts, excluded.start_ts), updated=excluded.updated""",
      (vid, title, channel, start_ts, status, time.time()))


def video(vid):
    return q("SELECT * FROM videos WHERE id=?", (vid,), one=True)


# ---- coverage (what part of the stream timeline is already handled) ----
def covered(video_id):
    """Merged list of [t0, t1] stream-time ranges that are downloaded (queued/processing/done)."""
    rows = q("SELECT t0, t1 FROM chunks WHERE video_id=? AND status IN ('queued','processing','done') ORDER BY t0",
             (video_id,))
    out = []
    for r in rows:
        if out and r["t0"] <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], r["t1"])
        else:
            out.append([r["t0"], r["t1"]])
    return out


def gaps(video_id, t_from, t_to, min_len=30):
    """Ranges in [t_from, t_to] not yet covered."""
    res, cur = [], t_from
    for a, b in covered(video_id):
        if b <= cur:
            continue
        if a > cur and a - cur >= min_len:
            res.append([cur, min(a, t_to)])
        cur = max(cur, b)
        if cur >= t_to:
            break
    if t_to - cur >= min_len:
        res.append([cur, t_to])
    return [g for g in res if g[1] - g[0] >= min_len]


def add_chunk(video_id, t0, t1, path, kind, status="queued"):
    return x("INSERT INTO chunks(video_id,t0,t1,path,kind,status,created) VALUES(?,?,?,?,?,?,?)",
             (video_id, t0, t1, str(path), kind, status, time.time()))


def retry_or_fail(cid, error):
    """First failure -> back in the queue once; second -> error (visible in the app)."""
    r = q("SELECT tries FROM chunks WHERE id=?", (cid,), one=True)
    if r and (r["tries"] or 0) < 1:
        x("UPDATE chunks SET status='queued', tries=tries+1, error=? WHERE id=?", (error, cid))
    else:
        x("UPDATE chunks SET status='error', error=? WHERE id=?", (error, cid))


def next_chunk():
    """Live chunks first (fresh clips post fastest), then backfill/VOD, oldest first inside each kind."""
    with _lock:
        r = q("""SELECT * FROM chunks WHERE status='queued'
                 ORDER BY CASE kind WHEN 'live' THEN 0 ELSE 1 END, created LIMIT 1""", one=True)
        if r:
            x("UPDATE chunks SET status='processing' WHERE id=?", (r["id"],))
        return r


def finish_chunk(cid, status="done", error=None):
    x("UPDATE chunks SET status=?, error=? WHERE id=?", (status, error, cid))


# ---- clips / dedupe ----
def overlaps_existing(video_id, start, end, max_overlap=0.25):
    rows = q("SELECT start, end FROM clips WHERE video_id=? AND end>? AND start<?", (video_id, start, end))
    for r in rows:
        inter = min(end, r["end"]) - max(start, r["start"])
        if inter > max_overlap * min(end - start, r["end"] - r["start"]):
            return True
    return False


def add_clip(**kw):
    kw.setdefault("status", "pending"); kw.setdefault("created", time.time())
    keys = ",".join(kw); qs = ",".join("?" * len(kw))
    return x(f"INSERT INTO clips({keys}) VALUES({qs})", tuple(kw.values()))


def next_clip_to_post(order="best_first", auto=False):
    """Clips you pressed 'Posteaza' on (status 'queued') go first; with auto-post also the pending ones."""
    o = "score DESC, created DESC" if order == "best_first" else "created DESC"
    r = q("SELECT * FROM clips WHERE status='queued' AND attempts<3 ORDER BY queued_at, created LIMIT 1", one=True)
    if r or not auto:
        return r
    return q(f"SELECT * FROM clips WHERE status='pending' AND attempts<3 ORDER BY {o} LIMIT 1", one=True)


def posts_since(ts):
    return q("SELECT COUNT(*) n FROM clips WHERE status='posted' AND posted_at>=?", (ts,), one=True)["n"]


def last_post_time():
    r = q("SELECT MAX(posted_at) t FROM clips WHERE status='posted'", one=True)
    return r["t"] or 0
