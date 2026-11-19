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
