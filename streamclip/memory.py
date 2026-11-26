"""Keeps RAM use low on weaker PCs.

- memory_mode: auto (low when the PC has < 12 GB RAM) / low / normal.
  low = small Whisper model in int8 (base under 8 GB RAM), 1 render at a time, fewer CPU threads, smaller beam.
- The Whisper model is loaded only when a chunk needs it and freed after model_idle_unload_minutes idle.
- ram_cap_gb (0 = off): above it the idle model is freed and new chunks wait (up to a minute) before starting.
"""
import gc, os, threading, time
from .util import cfg, log

_total = None
_warned = [0.0]


def total_gb():
    global _total
    if _total is None:
        try:
            import psutil
            _total = psutil.virtual_memory().total / 2 ** 30
        except Exception:
            try:
                _total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
            except (ValueError, OSError, AttributeError):
                _total = 16.0
    return _total


def rss_gb():
    """Resident memory of this process (MB precision)."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 2 ** 30
    except Exception:
        try:
            with open("/proc/self/statm") as f:
                return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2 ** 30
        except Exception:
            return 0.0


def low():
    m = str(cfg().get("memory_mode", "auto")).lower()
    if m == "low":
        return True
    if m == "normal":
        return False
    cap = float(cfg().get("ram_cap_gb", 0) or 0)
    return total_gb() < 12 or (0 < cap <= 6)


def cap_gb():
    return float(cfg().get("ram_cap_gb", 0) or 0)


def over_cap():
    c = cap_gb()
    return bool(c) and rss_gb() > c


def free():
    gc.collect()
    try:                                  # give freed heap back to the OS (glibc); no-op elsewhere
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def wait_for_room(stop=None, max_wait=60):
    """Before a new chunk: if over ram_cap_gb, free the idle model and wait a little for renders to finish."""
    if not over_cap():
        return True
    from . import transcribe
    transcribe.unload("RAM cap")
    end = time.time() + max_wait
    while over_cap() and time.time() < end:
        free()
        if stop is not None and stop.wait(2):
            return False
        if stop is None:
            time.sleep(2)
    if over_cap() and time.time() - _warned[0] > 1800:
        _warned[0] = time.time()
        log.warning("RAM use %.1f GB is above ram_cap_gb=%.1f; continuing slowly (try memory_mode: low)", rss_gb(), cap_gb())
    return True


def watch(stop):
    """Background: free the Whisper model when idle; keep an eye on the cap."""
    from . import transcribe
    while not stop.wait(30):
        try:
            idle = float(cfg().get("model_idle_unload_minutes", 10) or 0) * 60
            if idle and transcribe.idle_for() > idle:
                transcribe.unload(f"idle {idle / 60:.0f} min")
            if over_cap():
                transcribe.unload("RAM cap")
        except Exception as e:
            log.debug("memory watch: %s", e)
