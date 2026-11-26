"""Secrets (stream keys, OAuth tokens) encrypted by the operating system, never stored in plain text on Windows:
- small values (stream keys): Windows Credential Manager via `keyring` (DPAPI-protected), or DPAPI directly;
- token files: the JSON is encrypted with DPAPI (bound to your Windows user) and saved as "dpapi:<base64>".
Old plain-text token files are re-saved encrypted the first time they are read.
On Linux/macOS (development) a system keyring is used when present; token files fall back to owner-only files."""
import base64
import json
import os
from pathlib import Path

SERVICE = "StreamClipper"


class SecretError(Exception):
    pass


def dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    src, dst = BLOB(len(data), buf), BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(dst)):        # 0x1 = no UI
        raise SecretError("Windows could not encrypt/decrypt this secret (DPAPI)")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)


def keyring_mod():
    try:
        import keyring
        kr = keyring.get_keyring()
        mod = type(kr).__module__.lower()
        if "fail" in mod or "null" in mod:
            return None
        return keyring
    except Exception:
        return None


def save_json(path: Path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj).encode("utf-8")
    if os.name == "nt":
        path.write_text("dpapi:" + base64.b64encode(dpapi(raw, True)).decode(), encoding="ascii")
    else:
        path.write_bytes(raw)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def load_json(path: Path, default=None):
    path = Path(path)
    try:
        txt = path.read_text(encoding="utf-8").strip()
    except OSError:
        return default
    if txt.startswith("dpapi:"):
        try:
            return json.loads(dpapi(base64.b64decode(txt[6:]), False).decode("utf-8"))
        except Exception:
            return default
    try:
        obj = json.loads(txt)
    except ValueError:
        return default
    if os.name == "nt" and obj is not None:
        try:
            save_json(path, obj)                 # legacy plain-text file -> encrypted from now on
        except Exception:
            pass
    return obj


def describe():
    if os.name == "nt":
        return "Windows Credential Manager" if keyring_mod() else "Windows DPAPI"
    return "system keyring" if keyring_mod() else None
