"""Types and allowed ranges of every numeric/choice setting (config.yaml, config.local.yaml, settings.json, Settings UI).

cfg() runs sanitize() so a hand-edited config with a typo ("chunk_minutes: five", "daily_post_cap: -3") can't
crash a worker: the bad value is replaced by the default and logged once. The Settings page uses check() and
answers with a readable error instead.
"""
# key: (type, min, max, default)
NUM = {
    "check_live_every_sec": (int, 20, 3600, 60), "channel_check_every_sec": (int, 30, 3600, 90),
    "backfill_max_hours": (float, 0, 48, 12), "process_recent_vods": (int, 0, 6, 0), "vod_max_hours": (float, 0.1, 48, 12),
    "chunk_minutes": (float, 0.1, 30, 5), "video_max_height": (int, 360, 2160, 1080),
    "clip_min_sec": (float, 5, 120, 15), "clip_max_sec": (float, 10, 180, 45), "clip_target_sec": (float, 5, 180, 30),
    "clips_per_chunk_max": (int, 1, 20, 3), "min_score": (float, 0, 10, 0.9), "min_gap_between_clips_sec": (float, 0, 600, 20),
    "llm_min_score": (int, 0, 10, 5), "caption_size": (int, 40, 200, 108), "caption_words_per_line": (int, 1, 8, 3),
    "hook_seconds": (float, 0, 10, 2.5), "manual_min_gap_minutes": (float, 0, 240, 3), "hashtags_max": (int, 1, 10, 5),
    "recut_sources_max_gb": (float, 0, 2000, 15), "post_interval_min_minutes": (float, 1, 1440, 20),
    "post_interval_max_minutes": (float, 1, 1440, 30), "post_jitter_minutes": (float, 0, 120, 4),
    "daily_post_cap": (int, 0, 200, 45), "auto_post_min_viral": (int, 0, 100, 40), "dedupe_similarity": (float, 0.5, 1.0, 0.8),
    "dashboard_port": (int, 1024, 65535, 8777), "delete_after_post_days": (float, 0, 365, 1),
    "keep_raw_chunks_hours": (float, 0, 720, 0), "skipped_retention_days": (float, 0, 365, 7), "disk_budget_gb": (float, 1, 20000, 150),
    "max_parallel_renders": (int, 1, 4, 1), "rotate_min_gap_minutes": (float, 0, 1440, 30),
}
CHOICE = {
    "whisper_device": ("auto", "cuda", "cpu"),
    "whisper_model": ("auto", "large-v3", "large-v3-turbo", "medium", "small", "base", "tiny"),
    "whisper_compute_type": ("auto", "float16", "int8_float16", "int8", "float32"),
    "encoder": ("auto", "h264_nvenc", "libx264"), "theme": ("dark", "light"), "visibility": ("public", "private"),
    "layout": ("split", "blur", "fill"), "ui_language": ("en", "ro"), "post_order": ("viral_first", "newest_first"),
    "post_preset": ("sigur", "normal", "agresiv", "personalizat"), "browser_channel": ("chrome", "msedge", "chromium", ""),
}
BOOL = ("backfill_from_start", "use_llm", "llm_fix_transcript", "auto_cam", "overlay_texts", "censor_swears", "auto_post",
        "headless", "delete_after_post", "auto_update", "check_updates", "start_with_windows", "minimize_to_tray",
        "notifications", "onboarded", "rotate")
LIST = ("extra_urls", "extra_keywords", "hashtags", "extra_hashtags", "quiet_hours", "cam_box", "rotate_accounts")


def _num(k, v):
    t, lo, hi, _ = NUM[k]
    if isinstance(v, bool):
        raise ValueError
    x = t(float(str(v).strip().replace(",", ".")))
    if not lo <= x <= hi:
        raise ValueError
    return x


CLAMP = {"max_parallel_renders"}       # silently clamped in the UI (a slider); the rest answers with an error


def check(k, v, clamp=None):
    """-> clean value or raises ValueError('<key>: <why>')."""
    if k in NUM:
        try:
            if (k in CLAMP if clamp is None else clamp) and not isinstance(v, bool):
                t, lo, hi, _ = NUM[k]
                return t(min(hi, max(lo, float(str(v).strip().replace(",", ".")))))
            return _num(k, v)
        except (TypeError, ValueError):
            t, lo, hi, _ = NUM[k]
            raise ValueError(f"{k}: must be a {'whole ' if t is int else ''}number between {lo:g} and {hi:g}") from None
    if k in CHOICE and v not in CHOICE[k]:
        raise ValueError(f"{k}: one of {' / '.join(o for o in CHOICE[k] if o)}")
    return v


_warned = set()


def sanitize(c, log=None):
    """In place: bad values -> default (logged once per key/value)."""
    for k, (t, lo, hi, d) in NUM.items():
        if k in c:
            try:
                c[k] = _num(k, c[k])
            except (TypeError, ValueError):
                if log and (k, str(c[k])) not in _warned:
                    _warned.add((k, str(c[k]))); log.warning("setting %s=%r is invalid (%g–%g): using %g", k, c[k], lo, hi, d)
                c[k] = d
    for k, opts in CHOICE.items():
        if k in c and c[k] not in opts:
            if log and (k, str(c[k])) not in _warned:
                _warned.add((k, str(c[k]))); log.warning("setting %s=%r is not one of %s: using %s", k, c[k], opts, opts[0])
            c[k] = "normal" if k == "post_preset" else opts[0]
    for k in BOOL:
        if k in c and not isinstance(c[k], bool):
            c[k] = str(c[k]).strip().lower() in ("1", "true", "yes", "on", "da")
    for k in LIST:
        if k in c and not isinstance(c[k], list):
            c[k] = [x for x in str(c[k] or "").replace(",", " ").split() if x] if k != "cam_box" else None
            if c[k] is None:
                c.pop(k)
    if c.get("clip_min_sec", 0) > c.get("clip_max_sec", 1e9):
        c["clip_min_sec"], c["clip_max_sec"] = c["clip_max_sec"], c["clip_min_sec"]
    if c.get("post_interval_min_minutes", 0) > c.get("post_interval_max_minutes", 1e9):
        c["post_interval_max_minutes"] = c["post_interval_min_minutes"]
    return c
