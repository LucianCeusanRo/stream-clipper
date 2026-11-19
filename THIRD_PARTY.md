# Third-party code, assets and ideas

| project | license | what is used |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense | downloading live / DVR / VOD / chat (dependency) |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | speech-to-text (dependency) |
| [OpenCV](https://opencv.org) + [YuNet model (opencv_zoo)](https://github.com/opencv/opencv_zoo) | Apache-2.0 / MIT | face detection; the model file is bundled in `models/` |
| [Playwright](https://playwright.dev), [pywebview](https://pywebview.flowrl.com), [zig](https://ziglang.org) | Apache-2.0 / BSD / MIT | browser for optional posting, the app window, compiling the small `.exe` launcher |
| [Montserrat](https://github.com/JulietaUla/Montserrat) | OFL 1.1 (`fonts/OFL.txt`) | default caption font (has ă â î ș ț) |
| Anton, Bebas Neue, Archivo Black, Poppins, Bangers ([Google Fonts](https://fonts.google.com)) | OFL 1.1 (`fonts/OFL-*.txt`) | alternative caption fonts |
| [Twemoji (jdecked/twemoji)](https://github.com/jdecked/twemoji) | graphics CC-BY 4.0 (`assets/emoji/LICENSE-twemoji-graphics.txt`) | emoji in clips (© Twitter/X and Twemoji contributors) |
| sound effects (`assets/sfx`) | made for this project, synthesized by `make_sfx.py` | boom / whoosh / pop |

## Projects I learned from (ideas, no code copied into this repo)

| project | license | idea |
|---|---|---|
| [wkaisertexas/tiktok-uploader](https://github.com/wkaisertexas/tiktok-uploader) | MIT | browser-based upload flow; reimplemented here with a persistent profile |
| [Bodila51/gtavi-claudecode](https://github.com/Bodila51/gtavi-claudecode) | MIT | moment signals (loudness, chat, hype words), webcam-on-top layout. An earlier private version reused some of its code; the face detection and caption code in this repo were rewritten |
| [utkualsir/sharkyclips](https://github.com/utkualsir/sharkyclips) | MIT | laughter/scream detection, name glossary, LLM viral score |
| [gummybearansh/Auto-Clipper](https://github.com/gummybearansh/Auto-Clipper) | – | build-up before the peak + payoff after, cutting on natural pauses |
| [jekku0966/HighlightMiner](https://github.com/jekku0966/HighlightMiner) | MIT | combining audio + transcript + chat into one score, human review before export |
| [saifk6717/ClippingShorts](https://github.com/saifk6717/ClippingShorts) | see repo | live monitoring, LLM judge on top of free signals |
