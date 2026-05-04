# Polymarket BTC Agent — Setup Guide

## Prerequisites

- Python 3.10+
- A Polymarket account with API credentials
- An Anthropic API key

## Quick Start

```bash
# 1. Clone the repo
git clone <repo-url>
cd polymarket-agent

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the bot — the setup wizard launches automatically on first run
python btc_agent.py
```

The wizard will walk you through creating an account and entering your API keys.
Your credentials are encrypted with your password and stored at `~/.polymarket_bot/<username>/config.json` — **never inside the repo**.

---

## CLI Flags

| Flag | Description |
|------|-------------|
| `--paper` | Paper trading mode using simulated balance (default) |
| `--real` | Live trading mode — requires typing `CONFIRM` before starting |
| `--setup` | Re-run the setup wizard even if an account exists |
| `--reset` | Delete your local encrypted config (with confirmation prompt) |
| `--status` | Print current balance, win rate, and last 5 trades, then exit |
| `--force` | Bypass the 14:00–18:00 UTC session window |
| `--once` | Run a single trading cycle then exit |

### Examples

```bash
# Paper trade (safe, default)
python btc_agent.py --paper

# Check your stats without starting the bot
python btc_agent.py --status

# Live trading (requires CONFIRM prompt)
python btc_agent.py --real

# Re-run wizard to update credentials
python btc_agent.py --setup
```

---

## Updating

```bash
git pull
pip install -r requirements.txt   # in case dependencies changed
```

---

## Security Notes

- API keys are encrypted with AES-256 (Fernet) derived from your password via PBKDF2 (480,000 iterations).
- Your password is stored only as a bcrypt hash — it is never saved in plaintext.
- Never commit `.env` files or any file containing credentials.
- The `~/.polymarket_bot/` directory is intentionally outside the repo.

---

## Support

Open an issue in the repo if you encounter problems.
