# JackettSearchBot

Telegram bot for searching Jackett releases, posting full results to Telegraph, and checking PTP availability.

## Prerequisites

- Python 3.10+
- `pip` (latest)
- A Telegram bot token
- Jackett running and reachable from this machine

## Setup

1. Clone the repository and enter it.
```bash
git clone <your-repo-url>
cd JackettSearchBot
```

2. Create a virtual environment.

Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Windows (CMD):
```bat
python -m venv .venv
.\.venv\Scripts\activate.bat
```

macOS/Linux (bash/zsh):
```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Upgrade packaging tools and install dependencies.
```bash
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

4. Create `config.env` in the project root.
```env
TELEGRAM_TOKEN=your_telegram_bot_token
API_ID=your_telegram_api_id
API_HASH=your_telegram_api_hash
JACKETT_API_KEY=your_jackett_api_key
JACKETT_URL=http://localhost:9117
MAX_RESULTS=10
AUTHORIZED_CHAT_IDS=id1,id2,id3
OWNER_ID=your_telegram_id
AUTH_DB_PATH=auth.db
```

Notes:
- `AUTHORIZED_CHAT_IDS` is optional bootstrap data. On startup, those IDs are inserted into SQLite if missing.
- `AUTH_DB_PATH` controls where runtime authorization entries are stored.

## Run

```bash
python main.py
```

## Bot Commands

- `/start` : Verify bot access.
- `/release <query>` : Search releases (with inline Prev/Next pagination when results span multiple pages).
- `/release <query> -gp` : Search only Golden Popcorn releases.
- `/r <query>` : Short alias for `/release`.
- `/check` : Check PTP availability.
- `/auth [id]` : Owner-only. Authorize current chat by default, or an explicit ID.
- `/unauth [id]` : Owner-only. Remove authorization for current chat by default, or an explicit ID.
- `/unauthall` : Owner-only. Remove all authorized IDs from SQLite.
- `/authlist` : Owner-only. List IDs currently authorized in SQLite.
- `/whoami` : Show your user ID, chat ID, and current authorization reason.

`/auth` and `/unauth` target resolution:
- If ID is provided: uses that ID.
- Else if command is a reply to a user message: uses that user ID.
- Else: uses current chat ID.

Authorization rules:
- Access is granted if any one applies: owner, authorized chat ID, or authorized user ID.
- Because of that, removing one grant may still leave another grant active.
- `/unauthall` clears the DB grants only; owner access still remains active by design.

## Project Structure

- `jackett_bot/app.py` : Bot wiring and command registration.
- `jackett_bot/config.py` : Environment-based configuration.
- `jackett_bot/handlers/commands.py` : Telegram command handlers.
- `jackett_bot/services/auth.py` : SQLite authorization storage and lookups.
- `jackett_bot/services/jackett.py` : Jackett query and parsing logic.
- `jackett_bot/services/telegraph.py` : Telegraph page publishing.
- `jackett_bot/services/ptp.py` : PTP health check helper.
- `main.py` : Application entry point.

## Best Practices

- Keep secrets only in local `config.env`; do not commit tokens or API keys.
- Always run inside `.venv` to avoid global dependency conflicts.
- Use pinned versions in `requirements.txt` for reproducible deploys.
- Run the bot with a process manager in production (for example: `systemd`, Docker restart policy, or PM2).
- Rotate credentials immediately if they are ever exposed.
