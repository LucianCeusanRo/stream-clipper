# Security

- The app listens on `127.0.0.1` only; the dashboard is not reachable from other machines.
- Your API keys go in `.env`, your settings in `config.yaml`, and the TikTok browser session in `data/tiktok_profile`. All three are in `.gitignore`. Don't commit them and don't paste them in issues.
- The program never stores your TikTok password; you log in yourself in the Chrome window.

Found a security problem? Please open a private report via **Security → Report a vulnerability** on GitHub instead of a public issue.
