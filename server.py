#!/usr/bin/env python3
"""
SimplyHired Jobs API + Dashboard (Flask)

Endpoints:
  GET  /                     -> dashboard UI
  GET  /health               -> {"status": "ok"}
  GET  /info                 -> service metadata
  GET  /jobs?q=&loc=&pages=  -> JSON job results (cached 10 min)

Run locally:  python server.py
On Render:    gunicorn server:app  (see render.yaml / Procfile)
"""

import os
import time
import hashlib
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory

from scraper import scrape_jobs, http as proxy_session

app = Flask(__name__)

CACHE_TTL = 600  # seconds
MAX_PAGES = 5
_cache: dict[str, tuple[float, dict]] = {}


def _key(q: str, loc: str, pages: int) -> str:
    return hashlib.md5(f"{q}|{loc}|{pages}".encode()).hexdigest()


@app.route("/")
def dashboard():
    return send_from_directory(str(Path(__file__).parent / "templates"), "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/info")
def info():
    return jsonify({
        "service": "SimplyHired Jobs API",
        "version": "1.1",
        "endpoints": ["/", "/health", "/info", "/jobs?q=&loc=&pages="],
        "cache_ttl_seconds": CACHE_TTL,
        "max_pages": MAX_PAGES,
        "proxy_mode": "free" if not os.environ.get("PROXY_LIST") else "custom",
        "proxy_candidates": len(proxy_session.proxies),
        "proxies_used": proxy_session.rotated,
    })


@app.route("/jobs")
def jobs():
    q = request.args.get("q", "").strip()
    loc = request.args.get("loc", "usa").strip() or "usa"
    try:
        pages = max(1, min(MAX_PAGES, int(request.args.get("pages", 3))))
    except ValueError:
        pages = 3

    k = _key(q, loc, pages)
    now = time.time()
    if k in _cache and now - _cache[k][0] < CACHE_TTL:
        payload = dict(_cache[k][1])
        payload["cached"] = True
        return jsonify(payload)

    try:
        results, total = scrape_jobs(q, loc, pages)
    except Exception as e:
        return jsonify({"error": str(e), "jobs": [], "total": 0}), 502

    payload = {
        "query": q,
        "location": loc,
        "pages": pages,
        "total": total,
        "count": len(results),
        "jobs": results,
        "cached": False,
    }
    _cache[k] = (now, payload)
    return jsonify(payload)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
