# Contributing

Thanks for wanting to help. I'm a beginner, so clear bug reports and small pull requests are the most useful thing you can send.

## Ways to help

- **Report a bug**: open an issue with the *Bug report* template. Include your Windows version, GPU, the last lines of the 📜 Log tab, and what you expected.
- **Suggest a feature**: open an issue with the *Feature request* template, or start a thread in [Discussions](https://github.com/LucianCeusanRo/stream-clipper/discussions).
- **Add a language**: moment keywords live in `streamclip/detect.py` (`KEYWORDS` / `KEYWORDS_EN`), hook and title templates in `streamclip/texts.py`. A new language needs both, plus a test.
- **Translate the dashboard**: `streamclip/web/index.html` (English) and `index.ro.html` (Romanian).

## Development setup

```bash
git clone https://github.com/LucianCeusanRo/stream-clipper.git
cd stream-clipper
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt                   # needs ffmpeg on PATH for the render tests
python -m streamclip selftest --quick             # runs in a temp folder, never touches your data/
python tools/demo.py                              # synthetic demo + dashboard at http://127.0.0.1:8833
```

## Pull requests

1. One change per pull request, with a short description of what and why.
2. Run `python -m streamclip selftest --quick` before pushing. CI runs the same tests on Ubuntu.
3. Add or update a test when you change behaviour.
4. **Never commit** `config.yaml`, `.env`, cookies, anything from `data/` (recordings, clips, `state.db`, `tiktok_profile`), or real stream footage. Use the synthetic demo for screenshots.
5. Keep the "respect creators" defaults: auto-post off, credit text supported.

By contributing you agree that your contribution is licensed under the MIT license of this project.
