# Football Analyzer Agent

Automated daily football match analysis delivered to Telegram, running entirely on a self-hosted Linux VPS with no external AI API costs.

Every morning at **8:00 AM CST** the agent fetches today's fixtures from 11 competitions via [soccerdata/FBref](https://soccerdata.readthedocs.io), computes outcome probabilities with a **Poisson + Dixon-Coles model**, sends the data to a **local Ollama LLM** for narrative analysis in Spanish, and delivers two structured Telegram messages per match.

---

## Table of Contents

- [Architecture](#architecture)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Agent](#running-the-agent)
- [Backtesting](#backtesting)
- [VPS Deployment (systemd)](#vps-deployment-systemd)
- [Project Structure](#project-structure)
- [Statistical Model](#statistical-model)
- [Troubleshooting](#troubleshooting)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│               Daily Pipeline  ·  8:00 AM CST (APScheduler)       │
└──────────────────────────────────────────────────────────────────┘
                                    │
              ┌─────────────────────▼──────────────────────┐
              │                  data.py                    │
              │  soccerdata / FBref                         │
              │  • Today's fixtures (11 competitions)       │
              │  • Rolling team stats (last 20 matches)     │
              │  • Standings · H2H · league averages        │
              └─────────────────────┬──────────────────────┘
                                    │  stats dict
              ┌─────────────────────▼──────────────────────┐
              │                  model.py                   │
              │  Dixon-Coles Poisson                        │
              │  • λ_home / λ_away (expected goals)         │
              │  • 1X2 probabilities + implied odds         │
              │  • Over 2.5 / 3.5 · BTTS · most likely     │
              │    scoreline                                 │
              └────────────┬──────────────────┬────────────┘
                           │ probabilities     │ stats
              ┌────────────▼──────────────────▼────────────┐
              │                analyzer.py                  │
              │  POST /api/chat  →  Ollama (local LLM)      │
              │  format=json · temperature=0.1              │
              │  → key_factors · detailed_analysis          │
              │  → best_bet · value_bet · risk_level        │
              └─────────────────────┬──────────────────────┘
                                    │ analysis dict
              ┌─────────────────────▼──────────────────────┐
              │               formatter.py                  │
              │  Message 1 — Summary (1X2, goals, best bet) │
              │  Message 2 — Detail (form, H2H, analysis)   │
              └─────────────────────┬──────────────────────┘
                                    │
              ┌─────────────────────▼──────────────────────┐
              │                   bot.py                    │
              │  Telegram Bot API · parse_mode=Markdown     │
              │  Retry once on failure · 3 s between msgs   │
              └────────────────────────────────────────────┘
```

---

## Features

- **11 competitions** — Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League, MLS, Liga MX, Eredivisie, Primeira Liga
- **Poisson + Dixon-Coles model** — attack/defense strength indices, home advantage factor, low-score correction for 0-0 / 1-0 / 0-1 / 1-1
- **Full probability surface** — 1X2 with implied odds, Over/Under 2.5 & 3.5, BTTS, most likely scoreline, λ expected goals
- **Local LLM via Ollama** — no external API calls, no per-token costs; falls back to stats-only output when Ollama is unavailable
- **Backtesting engine** — replay any number of past seasons, evaluate 4 betting strategies, export match-level CSV + calibration report + strategy P&L summary
- **Production-ready** — rotating file logs, APScheduler with CST cron, systemd service config, graceful error handling throughout

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | 3.11 recommended |
| [Ollama](https://ollama.com) | Installed and running (`ollama serve`) |
| An Ollama model | See [Configuration](#configuration) for recommendations |
| Telegram Bot | Created via [@BotFather](https://t.me/BotFather) |
| Linux VPS | Ubuntu 22.04+ recommended |

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/chepe5251/footballAnalizer.git
cd footballAnalizer
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Pull an Ollama model

```bash
# Recommended — good balance of quality and speed
ollama pull llama3.1:8b

# Faster on CPU-only VPS (lower quality)
ollama pull llama3.2:3b

# Higher quality if your VPS has a GPU
ollama pull mistral:7b
```

Verify Ollama is running:

```bash
curl http://localhost:11434/api/tags
```

### 5. Configure environment variables

```bash
cp .env.example .env
nano .env
```

Fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. See [Configuration](#configuration) for all options.

### 6. Test run

```bash
python main.py
```

The pipeline runs immediately on first start, then schedules daily at 8:00 AM CST.

---

## Configuration

Copy `.env.example` to `.env` and set the following variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama API endpoint. Change if Ollama runs on a different host or port. |
| `OLLAMA_MODEL` | No | `llama3.1:8b` | Model name as shown by `ollama list`. Must be pulled before running. |
| `TELEGRAM_BOT_TOKEN` | **Yes** | — | Token from @BotFather (`123456:ABC-DEF...`). |
| `TELEGRAM_CHAT_ID` | **Yes** | — | Target chat ID. Can be a user ID or group/channel ID (prefix `-100` for channels). |
| `LOG_LEVEL` | No | `INFO` | Python log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

### Finding your Telegram Chat ID

1. Send any message to your bot.
2. Open: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Copy the `id` value from `result[0].message.chat.id`.

---

## Running the Agent

### Daily pipeline (foreground, with immediate first run)

```bash
source venv/bin/activate
python main.py
```

Logs are written to `logs/football_agent.log` (rotating, 5 MB × 3 backups) and to stdout.

### Manual single run (for testing)

The agent always executes the pipeline once at startup before entering the scheduler loop. Press `Ctrl+C` to stop.

---

## Backtesting

The backtesting module replays historical seasons using the same Poisson model, with a strict **rolling-window approach** (past 20 matches only) to prevent data leakage. It evaluates four betting strategies and exports three CSV files.

### Strategies

| Strategy | Description |
|---|---|
| **Threshold + Fixed Stake** | Bet `--stake` on the outcome the model is most confident about, only when `prob ≥ threshold`. |
| **Threshold + Kelly** | Same entry condition; stake sized by fractional Kelly criterion (capped at 20 % of bankroll). |
| **Value Bet + Fixed Stake** | Bet `--stake` when model `EV > 0` vs simulated market odds (+10 % bookmaker margin). |
| **Value Bet + Kelly** | Same EV condition; Kelly-sized stake. |

### Usage

```bash
# Premier League, last 2 completed seasons, default settings
python run_backtest.py

# Multiple leagues, 3 seasons, higher probability threshold
python run_backtest.py \
  --leagues "ENG-Premier League" "ESP-La Liga" \
  --seasons 3 \
  --threshold 0.60

# All supported leagues, custom stake and bankroll
python run_backtest.py \
  --leagues all \
  --seasons 2 \
  --stake 20 \
  --bankroll 2000 \
  --kelly-fraction 0.25 \
  --output my_test

# Single league, aggressive Kelly
python run_backtest.py \
  --leagues "GER-Bundesliga" \
  --seasons 2 \
  --kelly-fraction 0.5
```

### Output files

All files are written to `backtest_output/` with a timestamp suffix:

| File | Contents |
|---|---|
| `{prefix}_{ts}_matches.csv` | One row per match: probabilities, actual outcome, P&L per strategy |
| `{prefix}_{ts}_calibration.csv` | Predicted vs actual win rate in 10 % probability bins |
| `{prefix}_{ts}_summary.csv` | Per-strategy: total bets, win rate, ROI, max drawdown, profit factor, Brier score |

### Interpreting results

- **Brier Score** — lower is better; random baseline is ~0.50, a calibrated model sits around 0.20–0.28.
- **Calibration error** — average absolute difference between predicted probability and actual frequency in that bin. Under 5 % per bin is good.
- **Profit factor** — gross wins / gross losses. Values above 1.0 indicate a net-profitable strategy over the period.

> **Important:** backtest results reflect past performance on FBref data only. They do not account for real market odds, line movement, or the vig structure of any specific bookmaker.

---

## VPS Deployment (systemd)

Running as a systemd service ensures the agent restarts automatically after reboots or crashes.

### 1. Create the service file

```bash
sudo nano /etc/systemd/system/football-agent.service
```

Paste:

```ini
[Unit]
Description=Football Analyzer Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/footballAnalizer
ExecStart=/home/ubuntu/footballAnalizer/venv/bin/python main.py
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Adjust `User` and `WorkingDirectory` to match your VPS setup.

### 2. Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable football-agent
sudo systemctl start football-agent
```

### 3. Check status and logs

```bash
sudo systemctl status football-agent
tail -f logs/football_agent.log

# Or via journald
sudo journalctl -u football-agent -f
```

### Ollama as a service

If Ollama is not already running as a service, set it up so it starts before the agent:

```bash
# Ollama ships its own systemd unit on Linux
sudo systemctl enable ollama
sudo systemctl start ollama
```

Then update the `[Unit]` section of the agent service to add:

```ini
After=network-online.target ollama.service
Wants=network-online.target ollama.service
```

---

## Project Structure

```
footballAnalizer/
│
├── main.py              Entry point. APScheduler cron (8 AM CST) + immediate
│                        first run on startup. Orchestrates the full pipeline.
│
├── data.py              FBref scraper via soccerdata. Fetches today's fixtures
│                        and builds the stats dict (form, H2H, averages,
│                        standings). Uses difflib fuzzy matching for team names.
│
├── model.py             Dixon-Coles Poisson model. Computes λ_home / λ_away,
│                        builds a 9×9 score matrix, derives all market outputs.
│
├── analyzer.py          Sends pre-computed stats to a local Ollama instance
│                        (format=json). Validates and coerces the response.
│                        Falls back to a stats-only dict on any failure.
│
├── formatter.py         Builds the two Telegram message strings from the
│                        combined stats + probabilities + analysis dicts.
│
├── bot.py               Sends messages via the Telegram Bot API (httpx).
│                        Retries once on failure. Handles daily header/footer.
│
├── config.py            Loads and validates environment variables at import
│                        time. Fails fast if required vars are missing.
│
├── logger.py            Configures rotating file handler (5 MB × 3) + console
│                        handler. Imported as `from logger import log`.
│
├── backtest/
│   ├── runner.py        Main engine. Iterates league × season, builds rolling
│   │                    stats (no data leakage), calls model, runs strategies.
│   ├── strategies.py    Four betting strategies: threshold/value × fixed/Kelly.
│   ├── metrics.py       Calibration bins + per-strategy P&L metrics.
│   └── exporter.py      Writes three CSV files and prints a console summary.
│
├── run_backtest.py      CLI entry point for the backtesting module.
│
├── requirements.txt
├── .env.example         Template with all supported environment variables.
└── .gitignore
```

---

## Statistical Model

### Poisson model

The probability of each scoreline `(i, j)` is modeled as the product of two independent Poisson distributions:

```
P(home=i, away=j) = Poisson(i; λ_home) × Poisson(j; λ_away)
```

Where:

```
λ_home = home_attack × away_defense × league_avg_home × home_advantage_factor (1.15)
λ_away = away_attack × home_defense × league_avg_away

home_attack  = home_goals_scored_avg  / league_avg_home
home_defense = home_goals_conceded_avg / league_avg_away
away_attack  = away_goals_scored_avg  / league_avg_away
away_defense = away_goals_conceded_avg / league_avg_home
```

### Dixon-Coles correction

Low-scoring scorelines are systematically mispriced by a pure Poisson model. The Dixon-Coles (1997) correction adjusts the 0-0, 1-0, 0-1, and 1-1 cells:

| Scoreline | Correction factor |
|---|---|
| 0-0 | `1 − λ_home × λ_away × ρ` |
| 1-0 | `1 + λ_away × ρ` |
| 0-1 | `1 + λ_home × ρ` |
| 1-1 | `1 − ρ` |

`ρ = 0.1` (calibrated default). The matrix is renormalized to sum to 1 after correction.

### Kelly criterion

Stake sizing for Kelly strategies:

```
kelly_pct = (prob × odds − 1) / (odds − 1)
stake     = bankroll × kelly_pct × kelly_fraction
```

`kelly_fraction = 0.25` by default (quarter Kelly) to reduce variance. Stakes are capped at 20 % of bankroll regardless.

---

## Troubleshooting

**`Connection refused` when calling Ollama**

Ollama is not running. Start it with `ollama serve` or `sudo systemctl start ollama`. Verify with `curl http://localhost:11434/api/tags`.

**`model not found` error**

The model specified in `OLLAMA_MODEL` has not been pulled. Run `ollama pull llama3.1:8b` (or whichever model you configured).

**No matches found today**

FBref coverage for some competitions lags by a day, or the competition is in its off-season. The agent logs the exact failure per competition at `WARNING` level — check `logs/football_agent.log`.

**Telegram messages not arriving**

Confirm `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are correct. For group chats, make sure the bot has been added to the group and has permission to send messages. Channel IDs require the `-100` prefix.

**soccerdata rate-limit errors**

FBref imposes rate limits. The code already adds `time.sleep(2)` between requests. If you hit limits repeatedly, increase the sleep in `data.py` or run during off-peak hours. FBref data is cached locally in `~/.soccerdata/`.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
