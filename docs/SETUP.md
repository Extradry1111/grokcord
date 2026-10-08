# Setup guide (about 10 minutes, no coding)

You need three things: a **Discord bot token**, an **xAI API key**, and a place to run the bot (your computer, Docker, or Railway).

---

## 1. Create the Discord bot (3 min)

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**. Name it `grokcord` (or anything you like).
2. **General Information**: upload [`media/logo-512.png`](../media/logo-512.png) as the app icon if you want the orb.
3. Go to **Bot**:
   - Click **Reset Token** → copy it. This is your `DISCORD_TOKEN`. Treat it like a password.
   - Scroll to **Privileged Gateway Intents** and turn on **Message Content Intent**. grokcord needs it to read @mentions, replies, and `/tldr` history.
4. Go to **OAuth2 → General**, copy the **Client ID**, and open this link with your ID pasted in:

   ```
   https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&scope=bot+applications.commands&permissions=309237763072
   ```

   That permission number grants only what grokcord uses: View Channels, Send Messages, Send Messages in Threads, Create Public Threads, Embed Links, Attach Files, Read Message History. Nothing admin.

5. Pick your server → **Authorize**. The bot appears offline until you run it.

## 2. Get an xAI API key (2 min)

1. Go to [console.x.ai](https://console.x.ai), sign in, and add a payment method or credits.
2. **API Keys → Create API Key**. Copy it. This is your `XAI_API_KEY`.
3. Optional but smart: set a monthly spend limit in the console. grokcord also has its own daily caps (see below).

## 3. Run it (5 min)

Copy the example config and fill in the two keys:

```bash
git clone https://github.com/Extradry1111/grokcord
cd grokcord
cp .env.example .env      # then open .env and paste DISCORD_TOKEN and XAI_API_KEY
```

### Option A: your computer (Python 3.10+)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m grokcord
```

You should see `Logged in as grokcord#1234`. Leave the window open: the bot is online while it runs.

### Option B: Docker (runs 24/7, restarts itself)

```bash
docker compose up -d
docker compose logs -f   # watch it start; Ctrl+C to stop watching
```

Settings and usage live in a Docker volume, so updates don't wipe them.

### Option C: Railway (cloud, no computer needed)

1. Fork this repo on GitHub.
2. On [railway.com](https://railway.com): **New Project → Deploy from GitHub repo** → pick your fork. The included `railway.json` builds the Dockerfile.
3. **Variables**: add `DISCORD_TOKEN` and `XAI_API_KEY`.
4. Optional: add a **Volume** mounted at `/data` so settings survive redeploys.

Any host that runs a Docker container or a Python process works the same way (Fly.io, a VPS, a Raspberry Pi).

## 4. First test

- Slash commands can take **up to an hour** to show up in every server the first time. To see them instantly in one server, set `DEV_GUILD_ID` in `.env` to your server's ID (right-click the server icon → **Copy Server ID**, with Developer Mode on in Discord settings) and restart.
- Type `/help`, then try `@grokcord hey`.
- Right-click any message → **Apps → Fact-check with Grok**.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Missing DISCORD_TOKEN, XAI_API_KEY` | You didn't create `.env`, or it's in the wrong folder. Run from the repo root. |
| `PrivilegedIntentsRequired` | Turn on **Message Content Intent** (step 1.3). |
| Bot is online but ignores @mentions | Same as above, and check the bot can see and send in that channel. |
| Slash commands missing | Wait up to an hour, or set `DEV_GUILD_ID`. Re-invite with the link in step 1.4 if you skipped `applications.commands`. |
| "The xAI API key was rejected" | Re-copy `XAI_API_KEY` and check you have credits in the xAI console. |
| "Grok is rate-limited or out of credits" | Top up in the xAI console or wait a minute. |
| `/imagine` or a model errors after an xAI update | Set `GROK_MODEL` / `GROK_IMAGE_MODEL` in `.env` to a current model from [xAI's model list](https://x.ai/api). |
