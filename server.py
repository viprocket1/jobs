#!/usr/bin/env python3
"""
SimplyHired Jobs Dashboard (Flask) — instant-mode

User clicks Refresh → Render POSTs to Termux tunnel → Termux scrapes
synchronously → returns jobs JSON → Render displays.

Required env vars on Render:
  SCRAPER_URL      - public URL of Termux listener (e.g. https://xxx.trycloudflare.com)
  INGEST_TOKEN     - shared secret (must match Termux's INGEST_TOKEN)

Endpoints:
  GET  /                  dashboard UI
  GET  /health            {"status":"ok"}
  GET  /info              service metadata
  GET  /jobs              cached jobs (with optional q/loc filters)
  GET  /meta              last scrape metadata + history
  POST /scrape            {q, loc, pages} → proxies to Termux, caches result
  GET  /history           recent scrape calls (for debugging)
"""

import json
import os
import threading
import time
import hmac
import urllib.request
import urllib.error
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
JOBS_FILE = DATA_DIR / "jobs.json"
META_FILE = DATA_DIR / "meta.json"

SCRAPER_URL = os.environ.get("SCRAPER_URL", "").strip().rstrip("/")
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "").strip()

app = Flask(__name__)

# In-memory cache (also persisted to disk so it survives Render restarts)
_jobs_cache: list = []
_meta_cache: dict = {}
_history: deque = deque(maxlen=50)  # recent scrape calls for debugging
_cache_mtime: float = 0.0
_lock = threading.Lock()


def _atomic_write(path: Path, payload) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_data():
    global _cache_mtime
    with _lock:
        try:
            mtime = max(JOBS_FILE.stat().st_mtime, META_FILE.stat().st_mtime)
        except FileNotFoundError:
            return [], {}
        if mtime == _cache_mtime and _jobs_cache:
            return _jobs_cache, _meta_cache
        try:
            payload = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
            new_jobs = payload.get("jobs", [])
        except Exception:
            new_jobs = []
        try:
            new_meta = json.loads(META_FILE.read_text(encoding="utf-8"))
        except Exception:
            new_meta = {}
        _jobs_cache[:] = new_jobs
        _meta_cache.clear()
        _meta_cache.update(new_meta)
        _cache_mtime = mtime
        return _jobs_cache, _meta_cache


def _filter_jobs(jobs, q: str, loc: str):
    q_l = q.lower().strip()
    loc_l = loc.lower().strip()
    out = []
    for j in jobs:
        if q_l:
            hay = " ".join(str(j.get(k, "")) for k in ("title", "company", "snippet", "requirements")).lower()
            if q_l not in hay:
                continue
        if loc_l and loc_l not in (j.get("location", "") or "").lower():
            continue
        out.append(j)
    return out


def _proxy_scrape(q: str, loc: str, pages: int) -> tuple[dict | None, str]:
    """POST to Termux, return (response_dict, error_message)."""
    if not SCRAPER_URL:
        return None, "SCRAPER_URL not set on Render"
    body = json.dumps({"q": q, "loc": loc, "pages": pages}).encode("utf-8")
    req = urllib.request.Request(
        f"{SCRAPER_URL}/run",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {INGEST_TOKEN}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8")), ""
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_body = {}
        return None, f"Termux returned {e.code}: {err_body.get('error', str(e))}"
    except urllib.error.URLError as e:
        return None, f"Termux unreachable: {e.reason}"
    except Exception as e:
        return None, f"Scrape failed: {e}"


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    return send_from_directory(str(ROOT / "templates"), "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/info")
def info():
    jobs, _ = _load_data()
    return jsonify({
        "service": "SimplyHired Jobs Dashboard",
        "version": "3.0",
        "mode": "instant (Render → Termux tunnel)",
        "endpoints": ["/", "/health", "/info", "/jobs", "/meta", "/scrape", "/history"],
        "job_count": len(jobs),
        "scraper_configured": bool(SCRAPER_URL),
        "scraper_url": SCRAPER_URL if SCRAPER_URL else None,
    })


@app.route("/jobs")
def jobs():
    jobs_all, meta = _load_data()
    q = request.args.get("q", "").strip()
    loc = request.args.get("loc", "").strip()
    try:
        limit = max(1, min(500, int(request.args.get("limit", 100))))
    except ValueError:
        limit = 100
    filtered = _filter_jobs(jobs_all, q, loc)
    return jsonify({
        "query": q, "location": loc,
        "total": len(filtered),
        "count": min(limit, len(filtered)),
        "jobs": filtered[:limit],
        "last_scrape": meta.get("last_scrape"),
        "trigger_q": meta.get("trigger_q"),
    })


@app.route("/meta")
def meta_endpoint():
    _, meta = _load_data()
    return jsonify(meta)


@app.route("/scrape", methods=["POST"])
def scrape():
    """Synchronous: proxy to Termux, store result, return to caller immediately."""
    body = request.get_json(silent=True) or {}
    q = str(body.get("q", "")).strip()
    loc = str(body.get("loc", "remote")).strip() or "remote"
    try:
        pages = max(1, min(5, int(body.get("pages", 2))))
    except (ValueError, TypeError):
        pages = 2

    t0 = time.time()
    result, err = _proxy_scrape(q, loc, pages)
    elapsed = round(time.time() - t0, 2)

    if err or result is None:
        _history.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "q": q, "loc": loc, "pages": pages,
            "ok": False, "error": err or "unknown", "elapsed_s": elapsed,
        })
        return jsonify({"ok": False, "error": err or "unknown", "elapsed_s": elapsed}), 502

    jobs_in = result.get("jobs", []) or []
    meta_in = result.get("meta", {}) or {}

    # Merge with existing cache, dedupe by url
    jobs_all, existing_meta = _load_data()
    by_url = {j.get("url"): j for j in jobs_all if j.get("url")}
    for j in jobs_in:
        u = j.get("url")
        if u:
            by_url[u] = j
        else:
            by_url[id(j)] = j
    merged = sorted(by_url.values(), key=lambda x: x.get("scraped_at", ""), reverse=True)

    history = list(existing_meta.get("history", []))
    history.append({
        "at": meta_in.get("last_scrape") or datetime.now(timezone.utc).isoformat(),
        "fresh": len(jobs_in),
        "unique": len(merged),
        "trigger_q": q,
    })
    history = history[-30:]

    new_meta = {
        "last_scrape": meta_in.get("last_scrape") or datetime.now(timezone.utc).isoformat(),
        "queries": meta_in.get("queries", []),
        "total_unique": len(merged),
        "total_fresh": len(jobs_in),
        "host": meta_in.get("host", "termux"),
        "trigger_q": q,
        "history": history,
    }

    _atomic_write(JOBS_FILE, {"jobs": merged, "meta": new_meta})
    _atomic_write(META_FILE, new_meta)
    global _cache_mtime
    with _lock:
        _cache_mtime = 0.0

    _history.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "q": q, "loc": loc, "pages": pages,
        "ok": True,
        "fresh": len(jobs_in),
        "available": result.get("available"),
        "elapsed_s": elapsed,
    })

    return jsonify({
        "ok": True,
        "q": q, "loc": loc, "pages": pages,
        "elapsed_s": elapsed,
        "fresh": len(jobs_in),
        "available": result.get("available"),
        "total": len(merged),
        "jobs": jobs_in,
        "meta": new_meta,
    })


@app.route("/history")
def history():
    return jsonify({"calls": list(_history)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"[server] SCRAPER_URL={'set' if SCRAPER_URL else 'MISSING'}")
    print(f"[server] INGEST_TOKEN={'set' if INGEST_TOKEN else 'MISSING'}")
    app.run(host="0.0.0.0", port=port, debug=False)