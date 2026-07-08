# SimplyHired Job Scraper

A live job scraper for [SimplyHired](https://www.simplyhired.com) with a web dashboard and JSON API. Bypasses Cloudflare via `cloudscraper` and extracts jobs from SimplyHired's embedded Next.js JSON.

## One-Click Deploy to Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/viprocket1/jobs)

Click the button, connect your GitHub, and Render reads `render.yaml` to spin up the web service on the free plan. Once live, open the service URL to use the dashboard.

> Note: on Render's free plan the service sleeps after inactivity; the first request after sleep takes ~30s to wake.

## Features

- Live search by keyword + location with cursor-based pagination (dedup across pages)
- Dark web dashboard at `/`
- JSON API at `/jobs`
- 10-minute in-memory caching
- Handles SimplyHired data quirks (salary as list-or-empty-string, remote attributes, ratings)

## API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard UI |
| `GET /health` | Health check `{"status":"ok"}` |
| `GET /info` | Service metadata |
| `GET /jobs?q=&loc=&pages=` | Job results as JSON (pages 1-5) |

Example:
```
/jobs?q=python%20developer&loc=remote&pages=3
```

## Run Locally

```bash
pip install -r requirements.txt
python server.py        # dashboard at http://localhost:8000
```

Or the standalone CLI scraper (saves JSON + CSV + Markdown):
```bash
python scraper.py "python developer" remote 3
```

## Stack

Flask + gunicorn, cloudscraper. Pure Python, no native build deps.
