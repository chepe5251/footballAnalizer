# Football Analyzer Agent

Automated daily football match analysis delivered to Telegram, running entirely on a self-hosted Linux VPS with no external AI API costs.

Every morning at **8:00 AM CST** the agent fetches today's fixtures from 11 competitions via **Sofascore's public JSON API**, computes outcome probabilities with a **Poisson + Dixon-Coles model**, sends the data to a **local Ollama LLM** for narrative analysis in Spanish, and delivers two structured Telegram messages per match.

---

## Table of Contents

- [Architecture](#architecture)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Agent](#running-the-agent)
- [Data Source — Sofascore](#data-source--sofascore)
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
              │  Sofascore public REST API (no browser)     │
              │  • Today's fixtures, matched by exact        │
              │    tournament ID (11 competitions)           │
              │  • Form (last 5) · season averages · H2H    │
              │  • Standings · league-wide goal averages    │
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

> The **backtesting module** is a separate offline pipeline and intentionally uses a different data source (FBref via `soccerdata`) — see [Backtesting](#backtesting) for why.

---

## Features

- **11 competitions** — Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League, MLS, Liga MX, Eredivisie, Primeira Liga
- **Browser-free data layer** — talks directly to Sofascore's REST API over HTTPS; no Chrome/ChromeDriver/Selenium to install or keep working on a headless VPS
- **Poisson + Dixon-Coles model** — attack/defense strength indices, home advantage factor, low-score correction for 0-0 / 1-0 / 0-1 / 1-1
- **Full probability surface** — 1X2 with implied odds, Over/Under 2.5 & 3.5, BTTS, most likely scoreline, λ expected goals
- **Local LLM via Ollama** — no external API calls, no per-token costs; falls back to stats-only output when Ollama is unavailable
- **Backtesting engine** — replay any number of past seasons, evaluate 4 betting strategies, export match-level CSV + calibration report + strategy P&L summary
- **Production-ready** — rotating file logs, APScheduler with CST cron, systemd service config, graceful error handling throughout

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | 3.12 tested |
| [Ollama](https://ollama.com) | Installed and running (`ollama serve`) |
| An Ollama model | See [Configuration](#configuration) for recommendations |
| Telegram Bot | Created via [@BotFather](https://t.me/BotFather) |
| Linux VPS | Ubuntu 22.04+ recommended |
| Outbound HTTPS to `api.sofascore.com` | No browser, no API key — just network access |

No Chrome/Chromium install is required for the live daily pipeline. (The backtesting module still depends on Chrome — see [Backtesting](#backtesting).)

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

You can also sanity-check the data layer on its own, without touching Ollama or Telegram:

```bash
python data.py
```

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

Sofascore needs no API key, token, or credentials of any kind — `config.py` has nothing to configure for the data layer.

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

## Data Source — Sofascore

`data.py` calls Sofascore's public REST API (`https://api.sofascore.com/api/v1/`) directly, routed through `soccerdata`'s `Sofascore` reader so requests still benefit from its session reuse, retry-on-failure, and TLS-fingerprint handling (`tls_requests`). No browser is involved — this is the opposite of `soccerdata.FBref`, which drives a real headless Chrome instance and is the original reason this project moved away from FBref for the live pipeline.

### Why exact tournament IDs, not league names

`get_todays_matches()` filters Sofascore's worldwide daily event list down to our 11 competitions by **exact numeric `uniqueTournament` ID**, not by fuzzy-matching tournament name strings. Many countries have generically-named top divisions — "Premier League," "Primeira/Primera Liga," etc. — so name-based matching produces false positives (e.g. a Canadian Premier League fixture being misfiled as the English Premier League). The ID map lives at the top of `data.py`:

| Competition | Sofascore tournament ID(s) |
|---|---|
| Premier League | 17 |
| La Liga | 8 |
| Serie A | 23 |
| Bundesliga | 35 |
| Ligue 1 | 34 |
| Champions League | 7 |
| Europa League | 679 |
| MLS | 242 |
| Liga MX | 11621 (Apertura), 11620 (Clausura) |
| Eredivisie | 37 |
| Primeira Liga | 238 |

Liga MX has two IDs because Sofascore models the Mexican season as two separate tournaments per year rather than one continuous one.

Team names are matched with `difflib.get_close_matches` (fuzzy, cutoff 0.6) — that's a safe use case, since spelling variants of the same team ("Man United" vs "Manchester United") need to resolve to the same row, and the candidate pool is always scoped to a single league's roster rather than the whole world.

### Adding a competition

1. Find the country's Sofascore category ID: `GET /api/v1/sport/football/categories`.
2. List that category's tournaments: `GET /api/v1/category/{category_id}/unique-tournaments`.
3. Add the resulting `uniqueTournament` ID to `COMPETITIONS` in `data.py`.

### Off-season behavior

`get_todays_matches()` correctly returns `[]` when none of the 11 tracked competitions have fixtures that day (e.g. mid-June, when most European top flights are between seasons). This is expected behavior, not a bug — the daily pipeline sends a "no matches today" notification instead of erroring out.

### Rate limiting and resilience

- Every Sofascore call sleeps `2` seconds before the next one (`time.sleep(2)`), since `soccerdata` applies no automatic delay for this reader by default.
- Every individual API call is wrapped in its own try/except; a failure at any stage (today's schedule, season resolution, rounds, standings) is logged as a warning and falls back to partial or default stats rather than crashing the pipeline.
- `get_team_stats()` always returns the full stats dict shape, even when every field had to fall back to its default — `model.py` and `analyzer.py` can rely on the keys always being present.
- An in-process cache avoids re-fetching an entire season's worth of rounds more than once per run when several matches from the same league are analyzed back-to-back.

---

## Backtesting

The backtesting module replays historical seasons using the same Poisson model, with a strict **rolling-window approach** (past 20 matches only) to prevent data leakage. It evaluates four betting strategies and exports three CSV files.

> **Note:** unlike the live daily pipeline, the backtester (`backtest/runner.py`) still fetches historical data from **FBref** via `soccerdata.FBref`, not Sofascore. This is a deliberate, pre-existing split: FBref's season-schedule scraper is the data source the backtest engine and its rolling-stats logic were originally built and validated against, and it was out of scope for the Sofascore migration to also rewrite the backtester. If you run backtests on a headless VPS, you'll need a working Chrome/Chromedriver setup for this module specifically — see [Troubleshooting](#troubleshooting).

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
├── data.py              Sofascore data layer (REST API, no browser). Fetches
│                        today's fixtures by exact tournament ID and builds the
│                        stats dict (form, H2H, averages, standings). Uses
│                        difflib fuzzy matching for team names only.
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
│   ├── runner.py        Main engine. Fetches historical data from FBref (not
│   │                    Sofascore — see Backtesting), builds rolling stats
│   │                    (no data leakage), calls model, runs strategies.
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

When a team's averages are unavailable (Sofascore returned no data for them), the model falls back to league-average strength (ratio of 1.0) for that side rather than failing outright. League-wide averages themselves fall back to `1.5` (home) / `1.2` (away) goals per game when Sofascore's own season data can't be fetched.

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

**`Found 0 matches today` from the live pipeline**

First check whether it's actually off-season for all 11 tracked competitions (European top flights typically run August–May; MLS and Liga MX run on different calendars). Run `python data.py` directly to see the raw count and check `logs/football_agent.log` at `WARNING`/`ERROR` level for the underlying cause if it's not simply off-season — e.g. "Sofascore unreachable" means the API itself couldn't be reached, not that there were no fixtures.

**A match shows the wrong competition / wrong league**

This would mean a `uniqueTournament` ID changed or was mismapped. Verify the ID against `https://api.sofascore.com/api/v1/category/{category_id}/unique-tournaments` and update `COMPETITIONS` in `data.py` — see [Data Source — Sofascore](#data-source--sofascore).

**`Chrome not found!` (only relevant to backtesting)**

The live pipeline (`data.py`) doesn't use Chrome at all — Sofascore is fetched over plain HTTPS. This error can only come from `run_backtest.py`, which still depends on FBref's Selenium-based scraper. Install Google Chrome and make sure `soccerdata`/`undetected-chromedriver` can find it; on a headless VPS, install Chrome anyway (no display is required, only the binary).

**Telegram messages not arriving**

Confirm `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are correct. For group chats, make sure the bot has been added to the group and has permission to send messages. Channel IDs require the `-100` prefix.

**Sofascore rate-limit / repeated timeouts**

`data.py` already sleeps 2 seconds between consecutive Sofascore calls. If you still hit limits (heavy use, shared VPS IP with other Sofascore traffic), space out retries further or run the pipeline less frequently. There's no local cache for live data — every run fetches fresh.

---

## License

MIT License.
