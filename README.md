# JackettSearchBot

Telegram bot for searching Jackett releases with in-chat pagination.

## Prerequisites

- Python 3.10+
- `uv` installed (`https://docs.astral.sh/uv/`)
- A Telegram bot token
- Jackett running and reachable from this machine
- `ffmpeg` and `ffprobe` installed on the system (required for subtitle extraction)

## Setup

1. Clone the repository and enter it.
```bash
git clone <your-repo-url>
cd JackettSearchBot
```

2. Create the local environment and install dependencies with `uv`.
```bash
uv sync
```

Notes:
- `uv sync` creates a local `.venv` automatically.
- You usually do not need to activate it manually when using `uv run`.
- `rich` is used for colored, cleaner terminal logging.
- `tgcrypto` is installed automatically on Python 3.10-3.12; on 3.13+ it is skipped unless you have C++ build tools.

3. Create `config.env` from the template and fill values.
```bash
cp config.env.example config.env
```

```env
# Telegram Bot Configuration
TELEGRAM_TOKEN=your_bot_token_here
API_ID=123456
API_HASH=your_api_hash_here

# Jackett Configuration
JACKETT_API_KEY=your_jackett_api_key_here
JACKETT_URL=http://localhost:9117

# TMDb Configuration
TMDB_API_KEY=your_tmdb_api_key_here

# qBittorrent Configuration
QBITTORRENT_HOST=http://localhost:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=adminadmin
QBITTORRENT_CATEGORY=movies

# Webhook Configuration
WEBHOOK_HOST=127.0.0.1
WEBHOOK_PORT=8888

# Post-processing Configuration
INDEX_BASE_URL=https://myindex.com/
MEDIA_LOCAL_PATH=/downloads/
SUBTITLE_LANGUAGES=eng,spa

# Authorization
AUTHORIZED_CHAT_IDS=id1,id2,id3
OWNER_ID=123456789

# Bot Behavior
MAX_RESULTS=10
REDACT_AFTER_SECONDS=300

# Logging
LOG_FILE_PATH=logs/jackett_bot.log
CONSOLE_LOG_LEVEL=INFO
FILE_LOG_LEVEL=DEBUG
```

Notes:
- `AUTHORIZED_CHAT_IDS` is optional bootstrap data loaded from `config.env` on startup.
- `REDACT_AFTER_SECONDS` controls how many seconds release results stay visible before auto-redaction.
- `/auth` adds temporary in-memory authorization only. Those IDs are cleared when the bot restarts.
- `LOG_FILE_PATH` is where verbose rotating logs are written.
- `CONSOLE_LOG_LEVEL` and `FILE_LOG_LEVEL` accept `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`.

## Run

```bash
uv run python main.py
```

If required config values are missing, startup stops with an initialization error and asks you to fill `config.env` first.
If Telegram returns a startup flood wait, the bot exits with a clear message and expected wait time.

## qBittorrent Webhook Setup

To enable completion notifications, URL mapping, and subtitle extraction, configure qBittorrent to notify the bot when a torrent finishes.

In qBittorrent:
1. Go to **Tools > Options > Downloads**.
2. Scroll down to **Run external program on torrent completion**.
3. Enable it and enter the following command (adjust port if needed):

```bash
curl -s -X POST "http://localhost:8888/webhook/torrent-done" -H "Content-Type: application/json" -d "{\"hash\":\"%I\",\"name\":\"%N\",\"tags\":\"%G\",\"size\":\"%Z\",\"save_path\":\"%D\",\"content_path\":\"%F\"}"
```

## Bot Commands

- **Inline Search** : Type `@your_bot_username <query>` to search TMDb. Pressing a result will send `/release <imdb_id>` to the chat to search Jackett for that specific title.
- `/listtorrents` : View and manage active torrents added by the bot via an interactive auto-updating message.
- `/release <query>` : Search releases (with inline `PREV`/`NEXT` pagination when results span multiple pages).
- `/release <query> --gp` : Search only Golden Popcorn releases.
- `/auth [id]` : Owner-only. Temporarily authorize current chat by default, or an explicit ID (clears on restart).
- `/unauth [id]` : Owner-only. Remove temporary authorization for current chat by default, or an explicit ID.
- `/unauthall` : Owner-only. Remove all temporary in-memory authorizations.

`/auth` and `/unauth` target resolution:
- If ID is provided: uses that ID.
- Else if command is a reply to a user message: uses that user ID.
- Else: uses current chat ID.

Authorization rules:
- Access is granted if any one applies: owner, configured authorized ID, or temporary authorized ID.
- Because of that, removing one grant may still leave another grant active.
- `/unauthall` clears only temporary in-memory grants; configured IDs and owner access still remain active.

Rate limit behavior:
- Telegram `FloodWait` during normal bot operations is handled gracefully (send/edit/delete/callback paths).
- Temporary rate-limit responses are returned to users instead of crashing handler execution.

## Project Structure

- `jackett_bot/app.py` : Bot wiring and command registration.
- `jackett_bot/config.py` : Environment-based configuration.
- `jackett_bot/handlers/commands.py` : Telegram command handlers.
- `jackett_bot/services/auth.py` : In-memory authorization storage and lookups.
- `jackett_bot/services/jackett.py` : Jackett query and parsing logic.
- `main.py` : Application entry point.

## Best Practices

- Keep secrets only in local `config.env`; do not commit tokens or API keys.
- Run commands with `uv run ...` to avoid global dependency conflicts.
- Keep dependencies in `pyproject.toml` and run `uv lock` after dependency changes.
- Run the bot with a process manager in production (for example: `systemd`, Docker restart policy, or PM2).
- Rotate credentials immediately if they are ever exposed.
