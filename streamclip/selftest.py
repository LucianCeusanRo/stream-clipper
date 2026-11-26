"""`python -m streamclip selftest [--quick]`: runs the automated tests in an isolated temp folder
(never touches your real data/state.db or TikTok)."""
import os, subprocess, sys, tempfile
from pathlib import Path
from .util import ROOT


def main(quick=False):
    with tempfile.TemporaryDirectory(prefix="streamclip-test-") as tmp:
        env = dict(os.environ, CLIPPER_HOME=tmp, CLIPPER_CONFIG=str(Path(os.environ.get("CLIPPER_CONFIG", ROOT / "config.example.yaml"))),
                   CLIPPER_FONTS=str(ROOT / "fonts"), CLIPPER_MODELS=str(ROOT / "models"), CLIPPER_QUICK="1" if quick else "0",
                   PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
        r = subprocess.run([sys.executable, "-m", "unittest", "-v", "streamclip._tests"], env=env, cwd=str(ROOT))
        print("\nALL TESTS PASSED ✔" if r.returncode == 0 else "\nSOME TESTS FAILED ✘ (see above)")
        return r.returncode


def smoke(real_whisper=False):
    """`python -m streamclip smoke`: full pipeline on a generated sample + all web routes, in a temp folder whose
    path has spaces and non-ASCII letters. Exit code 1 on any failure or traceback."""
    with tempfile.TemporaryDirectory(prefix="streamclip smoke ăș ") as tmp:
        env = dict(os.environ, CLIPPER_HOME=tmp, CLIPPER_CONFIG=str(ROOT / "config.example.yaml"),
                   CLIPPER_FONTS=str(ROOT / "fonts"), CLIPPER_MODELS=str(ROOT / "models"), PYTHONIOENCODING="utf-8",
                   PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
        cmd = [sys.executable, "-m", "streamclip._smoke"] + (["--real-whisper"] if real_whisper else [])
        return subprocess.run(cmd, env=env, cwd=str(ROOT)).returncode
