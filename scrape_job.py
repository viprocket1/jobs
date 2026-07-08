#!/usr/bin/env python3
"""Background scrape job for Termux - writes data/jobs.json + data/meta.json."""

import argparse, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from scraper import scrape_jobs

DEFAULT_QUERIES = [
    ("python developer", "remote", 2),
    ("software engineer", "remote", 2),
    ("data engineer", "remote", 1),
    ("devops engineer", "remote", 1),
    ("frontend developer", "remote", 1),
]

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
JOBS_FILE = DATA_DIR / "jobs.json"
META_FILE = DATA_DIR / "meta.json"
RUNS_DIR = DATA_DIR / "runs"


def _load_existing():
    jobs, meta = [], {}
    if JOBS_FILE.exists():
        try:
            payload = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
            jobs = payload.get("jobs", [])
            meta = payload.get("meta", {})
        except Exception as e:
            print(f"  [warn] read failed: {e}")
    return jobs, meta


def _save(jobs, meta, write_snapshot=True):
    DATA_DIR.mkdir(exist_ok=True)
    RUNS_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    if write_snapshot:
        snap = RUNS_DIR / (now.strftime("%Y%m%d_%H%M%S") + ".json")
        snap.write_text(json.dumps({"scraped_at": now.isoformat(), "count": len(jobs), "jobs": jobs}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [save] snapshot -> data/runs/{snap.name}")
    JOBS_FILE.write_text(json.dumps({"jobs": jobs, "meta": meta}, ensure_ascii=False, indent=2), encoding="utf-8")
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [save] {len(jobs)} jobs -> data/jobs.json")


def _dedupe_by_url(jobs):
    by_url = {}
    for j in jobs:
        u = j.get("url") or ""
        if not u:
            continue
        prev = by_url.get(u)
        if not prev or j.get("scraped_at", "") > prev.get("scraped_at", ""):
            by_url[u] = j
    return sorted(by_url.values(), key=lambda x: x.get("scraped_at", ""), reverse=True)


def run(queries, write_snapshot=True):
    existing_jobs, existing_meta = _load_existing()
    print("[scrape_job] " + datetime.now().isoformat(timespec="seconds") + " - " + str(len(queries)) + " queries")

    fresh = []
    query_stats = []
    for q, loc, pages in queries:
        print("  -> q=" + repr(q) + " loc=" + repr(loc) + " pages=" + str(pages))
        t0 = time.time()
        try:
            results, total = scrape_jobs(q, loc, pages)
        except Exception as e:
            print("    ERROR: " + str(e))
            query_stats.append({"q": q, "loc": loc, "error": str(e), "elapsed_s": round(time.time() - t0, 1)})
            continue
        now_iso = datetime.now(timezone.utc).isoformat()
        for r in results:
            r["scraped_at"] = now_iso
            r["src_query"] = q
            r["src_location"] = loc
        fresh.extend(results)
        print("    " + str(len(results)) + " jobs (" + str(total) + " available) in " + str(round(time.time() - t0, 1)) + "s")
        query_stats.append({"q": q, "loc": loc, "pages": pages, "returned": len(results), "available": total, "elapsed_s": round(time.time() - t0, 1)})

    merged = existing_jobs + fresh
    deduped = _dedupe_by_url(merged)

    history = list(existing_meta.get("history", []))
    history.append({"at": datetime.now(timezone.utc).isoformat(), "fresh": len(fresh), "unique": len(deduped)})

    meta = {
        "last_scrape": datetime.now(timezone.utc).isoformat(),
        "queries": query_stats,
        "total_unique": len(deduped),
        "total_fresh": len(fresh),
        "host": os.uname().nodename,
        "history": history[-30:],
    }

    _save(deduped, meta, write_snapshot)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Background scrape job")
    ap.add_argument("--queries", nargs="+", metavar="SPEC", help="Override: 'query|location|pages'")
    ap.add_argument("--no-snapshot", action="store_true", help="Skip per-run snapshot file")
    args = ap.parse_args()

    queries = DEFAULT_QUERIES
    if args.queries:
        queries = []
        for spec in args.queries:
            parts = spec.split("|")
            q = parts[0] if parts else ""
            loc = parts[1] if len(parts) > 1 else "remote"
            try:
                pages = int(parts[2]) if len(parts) > 2 else 1
            except ValueError:
                pages = 1
            queries.append((q, loc, pages))

    return run(queries, write_snapshot=not args.no_snapshot)


if __name__ == "__main__":
    sys.exit(main())
