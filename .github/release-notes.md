**Stream Clipper v1.3.3: clip Kick, Twitch and YouTube streams into Shorts and TikToks.** Any streamer, game or language.

**⬇ Windows: download `StreamClipper-Setup.exe` and run it. Say Yes to the administrator prompt, then Next → Next → Install.**

- **Runs as administrator.** On some PCs parts of the setup failed without admin. The installer now runs as admin, turns on Windows long-path support (deep pip paths caused "file not found" errors) and creates a "Stream Clipper" scheduled task with highest privileges. Shortcuts, autostart and the post-install Launch start the app elevated **without a UAC prompt over your game**. Updates keep working (they run inside the elevated app). Want no admin? Put an empty `no-admin.txt` next to `Stream Clipper.exe`.
- **New: Channels.** Add Kick or Twitch channels. Each one is checked every 90 s (also from the tray). It records when the channel goes live, stops when the live ends and makes clips. Offline channels stay quiet, and errors or rate limits back off (1 → 30 min).
- **Fixed: Kick videos.** Kick changed its site and yt-dlp's Kick extractor broke ("NOT_FOUND"). Kick links now use Kick's public API (with yt-dlp as fallback), and error messages are short and readable.
- **New: Rotate posting.** Queued clips take turns across your TikTok / YouTube Shorts / Facebook Reels accounts. Each account keeps its own daily cap and minutes between posts, and the same clip never goes twice to one account. The planned schedule is shown in Queue. Auto-post stays **OFF** by default and nothing posts without your OK. Facebook Reels is **export only** (clip + caption + cover saved for a manual upload).
- **Uses less RAM.** Default speech model is `small` in int8 (`base` on PCs under 8 GB). A low-memory mode (auto under 12 GB RAM) handles one clip at a time, the model is freed after 10 idle minutes (~0.2 GB idle), and there is an optional RAM cap.
- **Cover frames.** The cover is the payoff moment by default, and you can pick any frame in the player.
- **No pop-ups over games.** The posting browser opens off-screen, no console windows appear, and audio re-syncs after Twitch ad breaks.
- **GPU fallback.** A CUDA/cuDNN error during transcription (e.g. GTX 10xx with new cuDNN) switches to the CPU instead of failing every chunk.
- **Every setting is validated** (types and ranges). A typo in config.yaml falls back to the default with a log line instead of crashing.
- New smoke test (full pipeline on a generated sample + every web route, fails on any traceback) runs in CI on Linux and Windows and before every release.

Unofficial fan tool, not affiliated with Rockstar Games or Take-Two. Built by a beginner with AI-assisted coding; limits are in the README.
