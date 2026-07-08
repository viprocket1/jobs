#!/usr/bin/env python3
"""
Termux-side HTTP listener. Runs persistently on Termux.

Exposes:
  POST /run  {q, loc, pages}
       -> scrapes the specified query, returns jobs JSON immediately
  GET  /health

Auth: requires "Authorization: Bearer <INGEST_TOKEN>" matching env var.

Run:
  INGEST_TOKEN=... python3 termux_listener.py

Then expose port 5000 to the internet via:
  cloudflared tunnel --url http://localhost:5000
  # or ngrok http 5000
"""

import os
import sys
import time
import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request, jsonify

from scraper import scrape_jobs

app = Flask(__name__)
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "").strip()
DATA_DIR = Path(__file__).parent / "data"


def _check():
    if not INGEST_TOKEN:
        return False, "INGEST_TOKEN not set on Termux"
    auth = request.headers.get("Authorization", "")
    provided = auth[7:] if auth.startswith("Bearer ") else ""
    if provided != INGEST_TOKEN:
        return False, "unauthorized"
    return True, ""


@app.route("/health")
def health():
    return jsonify({"status": "ok", "ts": datetime.now(timezone.utc).isoformat()})


@app.route("/run", methods=["POST"])
def run():
    ok, err = _check()
    if not ok:
        return jsonify({"error": err}), 401

    body = request.get_json(silent=True) or {}
    q = str(body.get("q", "")).strip()
    loc = str(body.get("loc", "remote")).strip() or "remote"
    try:
        pages = max(1, min(5, int(body.get("pages", 2))))
    except (ValueError, TypeError):
        pages = 2

    started = time.time()
    try:
        results, total = scrape_jobs(q, loc, pages)
    except Exception as e:
        return jsonify({"error": str(e), "q": q, "loc": loc}), 500

    now_iso = datetime.now(timezone.utc).isoformat()
    for r in results:
        r["scraped_at"] = now_iso
        r["src_query"] = q
        r["src_location"] = loc

    DATA_DIR.mkdir(exist_ok=True)
    meta = {
        "last_scrape": now_iso,
        "queries": [{"q": q, "loc": loc, "pages": pages,
                     "returned": len(results), "available": total,
                     "elapsed_s": round(time.time() - started, 1)}],
        "total_unique": len(results),
        "total_fresh": len(results),
        "host": os.uname().nodename,
        "trigger_q": q,
        "history": [],
    }
    payload = {"jobs": results, "meta": meta}
    (DATA_DIR / "jobs.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (DATA_DIR / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    return jsonify({
        "ok": True,
        "elapsed_s": round(time.time() - started, 1),
        "q": q,
        "loc": loc,
        "pages": pages,
        "available": total,
        "returned": len(results),
        "jobs": results,
        "meta": meta,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[termux_listener] INGEST_TOKEN={'set' if INGEST_TOKEN else 'MISSING'}")
    print(f"[termux_listener] listening on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)