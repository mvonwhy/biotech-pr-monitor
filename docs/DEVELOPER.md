# X PR Monitor (BioTech)

Near-real-time alerts when **BioStocks**, **BioPharmIQ**, or **BPharmCatalyst** post **original** tweets that mention tickers from your Trade Plan sheet — matched by **X Filtered Stream rules** and ingested via **GET `/2/tweets/search/stream`** (Pay Per Use). Enterprise webhook push is optional / unused here.

## Zero inference tokens (core path)

> **Monitoring consumes zero inference tokens; detection is X→webhook push only.**

Matching is performed by X stream rules. This service never polls X for tweets and never calls an LLM in the monitoring path. Optional analysis hooks that use models are **opt-in** (`ALLOW_INFERENCE_HOOKS=1`) and **disabled by default**.


## Active delivery mode (Pay Per Use)

**Stream mode** — `GET /2/tweets/search/stream` (long-lived HTTP) — is the active ingest path under **X Pay Per Use**. X charges **per matched post** on that connection. Rules stay on `POST/GET /2/tweets/search/stream/rules` (`scripts/run_filtered_stream.py`, optional `--sync-rules`).

**Webhook delivery** (`POST /2/tweets/search/webhooks/:id`) needs **Enterprise** enrollment; attach returned `403 client-not-enrolled` on non-Enterprise apps. The local FastAPI CRC receiver + cloudflared tunnel may still run but are unused for stream mode.

```bash
# Start filtered stream (foreground)
PYTHONPATH=. .venv/bin/python scripts/run_filtered_stream.py

# Background
mkdir -p logs
nohup env PYTHONPATH=. .venv/bin/python scripts/run_filtered_stream.py >> logs/stream.log 2>&1 &
# Stop: kill $(pgrep -f run_filtered_stream)
# Status: curl -s localhost:8787/stream/status   # if uvicorn is up
```

## Architecture

```
┌─────────────────┐     Filtered Stream rules      ┌──────────────────────┐
│  Trade Plan     │  (from:SOURCE + $TICKER /      │  X platform          │
│  Sheet Ticker   │───► TICKER -is:reply           │  Filtered Stream     │
│  (2×/day sync)  │     -is:retweet -is:quote)     │  Webhooks (push)     │
└─────────────────┘                                └──────────┬───────────┘
                                                              │ HTTPS POST
                                                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Local FastAPI receiver  GET/POST /webhooks/x                           │
│  1. CRC (GET) + signature verify (POST)                                 │
│  2. Drop non-originals (reply / RT / quote)                             │
│  3. Resolve press-release URL (redirects + domain/path heuristics)      │
│  4. Analysis hooks (noop / plugins; LLM hooks opt-in, off by default)   │
│  5. Append logs/alerts.jsonl + in-memory GET /alerts                    │
└─────────────────────────────────────────────────────────────────────────┘
```

Mermaid:

```mermaid
flowchart LR
  Sheet[Trade Plan Sheet Ticker] -->|08:12 and 16:12 ET| Cache[tickers.json]
  Cache -->|rebuild rules| Rules[Filtered Stream rules]
  Rules --> X[X Filtered Stream Webhooks]
  X -->|POST originals only| WH[/webhooks/x]
  WH --> F[Drop reply/RT/quote]
  F --> PR[Resolve PR URL]
  PR --> H[Analysis hooks]
  H --> Log[alerts.jsonl]
```

**Ticker ≠ handle.** The sheet `Ticker` column is stock symbols (`MRNA`). The three X accounts that *post* PR chatter are fixed in `config/source_accounts.json`.

## What you must provide

1. **X Developer App** at [developer.x.com](https://developer.x.com)
   - Project + App with access that includes **Filtered Stream** and **Filtered Stream Webhooks** (plan-dependent: Basic / Pro / etc.).
   - **Consumer Key / Secret** (`X_API_KEY`, `X_API_SECRET`) — secret used for CRC HMAC + `x-twitter-webhooks-signature`.
   - **Bearer Token** (`X_BEARER_TOKEN`) — rules + webhook registration only (not tweet polling).
2. **Public HTTPS URL** for the receiver (no port in the registered URL). In local dev, tunnel with **ngrok** or **Cloudflare Tunnel** to `http://127.0.0.1:8787`, then set:
   `PUBLIC_WEBHOOK_URL=https://<tunnel-host>/webhooks/x`
3. **Ticker source** (read-only):
   - Google service-account JSON with Sheets **read** access to spreadsheet `1Xa4HDvSMC5HxG7G92tOQOIeDlF2AP-F32hwbwvrHPlw` tab `2026` column `Ticker`, **or**
   - Manual CSV via `scripts/sync_tickers_from_csv.py`, **or**
   - Drop JSON into `config/tickers.json` (e.g. after a Drive connector export).

True X Account Activity webhooks require each monitored user to authorize your app. We do **not** use AAAPI for third-party accounts; we use **Filtered Stream Webhooks** on public posts from the three source accounts.

## Stream rule syntax

Each rule (chunked to stay under ~480 chars):

```text
(from:BioStocks OR from:BioPharmIQ OR from:BPharmCatalyst) ($MRNA OR MRNA OR $GILD OR GILD ...) -is:reply -is:retweet -is:quote
```

- `$TICKER` — cashtag  
- `TICKER` — bare keyword (short tickers may over-match)  
- `-is:reply -is:retweet -is:quote` — originals only at the X edge  
- Receiver also drops reply/RT/quote if anything slips through  


## Secrets with 1Password (required for X API keys)

Do **not** put plaintext `X_API_KEY` / `X_API_SECRET` / `X_BEARER_TOKEN` in `.env`.
Store them in a 1Password item and reference fields with the CLI:

```text
op://<Vault>/<Item-Name-or-UUID>/<field>
```

Example `.env` (see `.env.example`):

```bash
OP_X_API_ITEM_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
X_API_KEY=op://Private/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/username
X_API_SECRET=op://Private/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/credential
X_BEARER_TOKEN=op://Private/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/bearer
```

### Dependency

- Install the **1Password CLI** (`op`): https://developer.1password.com/docs/cli/get-started/
- Sign in: `op signin` (or enable the 1Password desktop app)
- This package shells out to `op read` at process start (`src/secrets.py`). No 1Password Python SDK is required.
- Alternate: `op run --env-file=.env -- uvicorn src.app:app --host 127.0.0.1 --port 8787`

### Verify

```bash
python scripts/verify_op_secrets.py
# then start the app — lifespan refuses to boot without X_API_SECRET
uvicorn src.app:app --host 127.0.0.1 --port 8787
```

## Setup

```bash
cd /workspace/x-pr-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: use op:// refs for X secrets (see 1Password section) — never commit plaintext keys
```

Optional Google Sheets client:

```bash
pip install google-api-python-client google-auth
```

## Run

**1. Webhook receiver** (sole post-ingest path):

```bash
cd /workspace/x-pr-monitor
source .venv/bin/activate
uvicorn src.app:app --host 127.0.0.1 --port 8787
```

**2. Tunnel** (local):

```bash
ngrok http 8787
# PUBLIC_WEBHOOK_URL=https://<id>.ngrok-free.app/webhooks/x
```

**3. Load tickers** (CSV if no Google creds yet):

```bash
python scripts/sync_tickers_from_csv.py /path/to/export.csv --sync-rules
# or one-shot sheet+rules:
python scripts/refresh_tickers_and_rules.py
```

**4. Register webhook + link Filtered Stream + sync rules:**

```bash
python scripts/register_webhook.py
```

**5. Twice-daily ticker refresh only** (filter maintenance — not post detection):

```bash
python -m src.scheduler
# default America/New_York 08:12 and 16:12
```

**CLI:**

```bash
python -m src.watchlist accounts list
python -m src.watchlist tickers list
python -m src.watchlist tickers add MRNA
python -m src.watchlist rules preview
```

## Resilience / auto-recovery

There is **no systemd unit**. After a cloud computer reset or process death, recover with the idempotent ensure script (health-checks uvicorn, cloudflared, Filtered Stream rules, and the stream client; writes `logs/watchdog_last.json`).

```bash
cd /workspace/x-pr-monitor
./scripts/ensure_stack.sh
# exit 0 = stack healthy; exit 1 = still broken (see logs/watchdog_last.json)
cat logs/watchdog_last.json
```

Optional forever loop (every 60s):

```bash
nohup ./scripts/watchdog_loop.sh >> logs/watchdog.log 2>&1 &
# stop: kill $(pgrep -f watchdog_loop.sh)
```

**Crontab:** this box often has no `crontab`/`cron`. If available, install:

```cron
*/5 * * * * /workspace/x-pr-monitor/scripts/ensure_stack.sh >> /workspace/x-pr-monitor/logs/watchdog.log 2>&1
```

If crontab is unavailable, leave recovery to the agent routine (one-shot `ensure_stack.sh` + optional `watchdog_loop.sh`). Do not sync X rules unless `rule_count` is 0 (`scripts/ensure_rules.py`).

## Pending alerts for chat notification

`logs/alerts.jsonl` is consumed with a byte-offset cursor so a notifier can
retry safely without the monitor advancing state. Read pending alerts without
changing the cursor:

```bash
cd /workspace/x-pr-monitor
PYTHONPATH=. .venv/bin/python scripts/pending_alerts_for_notify.py
```

The command prints `{"new": [...], "next_cursor": ...}`. After the notifier
has successfully handled the returned alerts, pass `--advance` on the next
read to persist the cursor; the helper does not restart the stream.

## Forwarding to a Grok Bot routine

Point a small reverse proxy or add a forwarder that, on each accepted alert, `POST`s the JSON to your Grok Bot routine webhook. Keep CRC/signature handling on this receiver; forward the **normalized** alert (`press_release_url`, etc.), not the raw X CRC traffic.

## Press-release URL resolution

Heuristics only (no LLM): expand `entities.urls` / text links → follow redirects (httpx) → prefer Business Wire, GlobeNewswire, PR Newswire, Accesswire, and IR `/news-releases` path patterns. Fields on each alert:

| Field | Meaning |
|---|---|
| `press_release_url` | Canonical PR URL or `null` |
| `press_release_title` | `<title>` if cheaply fetched |
| `pr_link_status` | `resolved` / `no_urls_in_tweet` / `urls_but_no_pr_match` |

## Monitoring: source race tracking

To decide which of the three source accounts to keep, the pipeline records **who posts each story first**.

- After press-release URL resolve, each alert is fingerprinted (prefer normalized `press_release_url` host+path; else cashtags + short text) and logged to `logs/source_race.jsonl`.
- Aggregate per-source stats (`first_place_count`, `total_seen`, avg/median lag when not first) live in `logs/source_stats.json` and at **`GET /source-stats`**.

```bash
curl -s http://127.0.0.1:8787/source-stats | python3 -m json.tool
# or: cat logs/source_stats.json
```

## Analysis hooks

- Protocol: `AnalysisHook.run(alert) -> alert` under `src/analysis_hooks/`
- Default / example plugins are non-LLM (`uses_inference=False`)
- Drop modules in `src/analysis_hooks/plugins/` that call `register_hook(...)`
- Entry points group: `x_pr_monitor.analysis_hooks`
- **LLM hooks require `ALLOW_INFERENCE_HOOKS=1`** — off by default so monitoring stays at **zero inference tokens**

## Env vars

See `.env.example`. Critical: `X_API_SECRET`, `X_BEARER_TOKEN`, `PUBLIC_WEBHOOK_URL`, sheet/CSV ticker settings.

## Limitations / blockers

- Live end-to-end stream delivery needs a **real Bearer token**, plan that includes Filtered Stream Webhooks, and a **public HTTPS** URL that can answer CRC.
- Rule count/length caps depend on your X plan; large ticker lists are auto-chunked.
- Bare ticker keywords can false-positive on short symbols; prefer cashtags when sources use `$TICKER`.
- Google Sheet sync needs a service account (or use CSV / Drive→local file). **Never writes back** to the sheet.
- Long-lived Filtered Stream *sockets* are **not** used in production (webhook/push only). A socket client would only be a last-resort fallback if your plan lacks webhooks — not shipped as the default path.

## Tests

```bash
python -m compileall src
python tests/test_crc.py
```
