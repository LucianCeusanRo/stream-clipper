**Stream Clipper v1.4.1: stream card, multistream for your own live, native Twitch clips.**

**⬇ Windows: download `StreamClipper-Setup.exe` and run it** (say Yes to the administrator prompt). If you already have it installed, the app updates itself.

- 🪪 **Stream card on posted and exported clips** from Kick or Twitch: logo, channel name, 🔴 LIVE and 👀 viewers while the channel is live, and 👥 followers. The numbers come straight from Kick or Twitch; anything missing is left out, never estimated. The card sits top-left, clear of TikTok's buttons, and appears after the hook. The channel link goes in the description. Each part can be switched off in Settings → Posting.
- 🗣️ **Titles in the streamer's own words.** The post title is now a line the streamer actually said in that clip, plus one emoji and 🎮 the real game. Generic lines like "Watch till the end" are gone. On-video captions are unchanged (no longer than before).
- 📡 **Multistream (your own live only).** Point OBS at `rtmp://127.0.0.1:1935/live` and the app sends the same stream to YouTube, Twitch and Kick at once. It's local and free, with no re-encode. Stream keys are encrypted by Windows (Credential Manager / DPAPI) and never written to files or logs. The relay only accepts OBS on your PC, so it can't restream someone else's channel.
- 🟣 **Native Twitch clips.** Highlights can become real Twitch clips through Twitch's official API ("Create Clip From VOD", still in beta at Twitch). It only works on your channel or channels where you're an editor. You sign in with a code on twitch.tv/activate and need your own free Twitch app (Client ID). There's a 🟣 button in the player, and an automatic option that's off by default.
- ▶️ **YouTube Shorts** keeps using the official YouTube Data API. OAuth tokens are now stored encrypted (old token files are converted automatically).
- 🟢 **Kick accounts are export only.** Kick has no public upload or clip API, so the clip and caption are saved to Exports and an "Open Kick" button takes you there. No scraping, no unofficial uploads.
- 🎞️ **Gallery**: hover a clip to preview it. Every clip shows its status (👀 to review, ⏳ queued, ✅ posted, 📦 exported) and the account it went to.
- Everything from v1.3.3 still works the same: auto-post stays off and nothing goes out without your OK.

Unofficial fan tool, not affiliated with Rockstar Games, Take-Two, Kick, Twitch, YouTube or TikTok. Built by a beginner with AI-assisted coding; limits are in the README.
