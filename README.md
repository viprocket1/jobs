# SimplyHired Jobs Dashboard

Live job scraper for [SimplyHired](https://www.simplyhired.com). Termux runs the scraper (residential IP bypasses Cloudflare), Render serves a web dashboard that proxies live to Termux via a public tunnel.

**Press a button → fresh jobs in ~2-3 seconds.** No cron, no polling.

```
┌──────────────┐    HTTPS (tunnel)     ┌──────────┐      ┌──────────┐
│   Browser    │──────────────────────▶│  Render  │─────▶│  Termux  │
│  (dashboard) │                        │  Flask   │  ◀───│  scraper │
└──────────────┘◀────── jobs JSON ─────┴──────────┘      └──────────┘
```

## Architecture

- **Termux**: runs `termux_listener.py` (Flask) + a public tunnel (Cloudflare or ngrok)
- **Render**: serves the dashboard, proxies `/scrape` calls to Termux synchronously
- **You**: open the dashboard URL, type query, hit "Refresh from Termux" → jobs appear in ~2s

No cron. No background loops. No git-based data sync. Pure request/response.

## Setup

### 1. One-time: deploy Render

Click the Deploy to Render button in this repo, or import manually. Then in Render Dashboard → Environment, set:

| Var | Value | Notes |
|-----|-------|-------|
| `INGEST_TOKEN` | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` | paste the same value into Termux later |
| `SCRAPER_URL` | leave blank for now | you'll set this after starting the tunnel |

### 2. Termux: install + run

```bash
pkg install cloudflared python   # if not already
cd /data/data/com.termux/files/home/sjob
pip install -r requirements.txt

export INGEST_TOKEN="<paste the same token you set on Render>"

./start_tunnel.sh
```

The script prints a public URL like `https://random-words.trycloudflare.com`. Copy it.

### 3. Render: finalize

Set `SCRAPER_URL=<paste the URL>` in Render Environment. Render will auto-redeploy (or click Manual Deploy).

### 4. Test

Open your Render dashboard URL. Type `nurse` in the keyword field, click **Refresh from Termux**. Jobs should appear in ~2-3 seconds.

## Files

- `scraper.py` — low-level SimplyHired scraper (proxy rotation, JSON extraction)
- `scrape_job.py` — multi-query batch runner (used for backup CLI)
- `termux_listener.py` — Flask listener on Termux, exposes `POST /run`
- `start_tunnel.sh` — boots listener + cloudflared/ngrok, prints public URL
- `server.py` — Render-side dashboard + `/scrape` proxy
- `templates/index.html` — dark UI with search + Refresh button
- `data/` — gitignored; created at runtime

## Endpoints

**Render** (`https://jobs-32s4.onrender.com`):
- `GET /` — dashboard
- `GET /health` — `{"status":"ok"}`
- `GET /info` — service metadata
- `GET /jobs?q=&loc=&limit=` — current dataset
- `GET /meta` — last scrape info + history
- `POST /scrape` `{q, loc, pages}` — synchronous proxy to Termux (~2-3s)
- `GET /history` — recent `/scrape` calls

**Termux** (via tunnel):
- `GET /health`
- `POST /run` `{q, loc, pages, Authorization: Bearer <token>}` — returns jobs JSON

## CLI (still works)

```
python scraper.py "python developer" remote 3
python scrape_job.py --queries "nurse|austin, tx|1"
```

## Notes

- Render free plan sleeps after 15 min idle → first request after sleep takes ~30s.
- Termux must stay on and Termux:API notifications enabled, otherwise the tunnel drops. If the tunnel URL changes, update Render's `SCRAPER_URL`.
- `cloudflared` quick tunnels give a new random URL each time you start. For a stable URL, sign up for a named Cloudflare Tunnel (free).
- For a "always-on" experience, run Termux in a wake-lock (`termux-wake-lock`) and the listener in the background.