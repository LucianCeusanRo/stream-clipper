#!/bin/sh
# Cross-build "Stream Clipper.exe" from Linux/macOS (pip install ziglang)
cd "$(dirname "$0")"
python3 -m ziglang cc -target x86_64-windows-gnu -O2 -s -municode -Wl,--subsystem,windows \
  launcher.c launcher.rc -o "../Stream Clipper.exe" -lshell32 -luser32 -ladvapi32 && rm -f ../*.pdb && echo OK
