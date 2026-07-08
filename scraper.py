#!/usr/bin/env python3
"""
SimplyHired Job Scraper
Usage: python scraper.py [query] [location] [pages]

Examples:
  python scraper.py "python developer" remote 3
  python scraper.py "nurse" "austin, tx" 5
  python scraper.py                        # all jobs, usa, 3 pages
"""

import re
import json
import time
import csv
import ast
import argparse
from datetime import datetime
from urllib.parse import urlencode, unquote

import cloudscraper

BASE_URL = "https://www.simplyhired.com/search"
SITE = "https://www.simplyhired.com"
TIMEOUT = 25
REQUEST_DELAY = 2.0

session = cloudscraper.create_scraper()


# ── URL builder (cursor-based pagination) ────────────────────────────────────

def build_url(query: str, location: str, cursor: str = "") -> str:
    params = {"q": query, "l": location}
    if cursor:
        params["cursor"] = cursor
    return f"{BASE_URL}?{urlencode(params, safe='')}"


# ── Parse one job object into a flat dict ────────────────────────────────────

def parse_job(job: dict) -> dict:
    # salaryInfo can be a list OR an empty string '' — always guard type
    salary_info = job.get("salaryInfo")
    if isinstance(salary_info, list) and salary_info:
        salary = salary_info[0].get("salary", "Not specified")
    else:
        salary = str(salary_info) if salary_info else "Not specified"

    # remoteAttributes may be a real list or a string like "['Remote']"
    remote_raw = job.get("remoteAttributes", [])
    if isinstance(remote_raw, str):
        try:
            rc = ast.literal_eval(remote_raw)
            remote = rc if isinstance(rc, list) else ([rc] if rc else [])
        except Exception:
            remote = [remote_raw] if remote_raw and remote_raw not in ("[]", "") else []
    else:
        remote = list(remote_raw) if remote_raw else []

    rating = job.get("companyRating")
    rating = rating if isinstance(rating, (int, float)) and rating >= 0 else None

    return {
        "title":       job.get("title", "N/A"),
        "company":     job.get("company", "N/A"),
        "location":    job.get("location", "N/A"),
        "salary":      salary,
        "job_types":   ", ".join(job.get("jobTypes", []) or []),
        "remote":      ", ".join(remote),
        "rating":      rating if rating is not None else "",
        "snippet":     (job.get("snippet", "") or "").strip(),
        "requirements": ", ".join(job.get("requirements", []) or []),
        "date_posted": job.get("dateOnIndeed", ""),
        "sponsored":   job.get("sponsored", False),
        "url":         SITE + unquote(job.get("encodedUrl", "")),
    }


# ── Extract jobs + page cursors from a response ──────────────────────────────

def extract(resp_text: str):
    m = re.search(
        r'<script[^>]*type="application/json"[^>]*>([^<]+)</script>',
        resp_text, re.DOTALL,
    )
    if not m:
        return [], "", {}
    data = json.loads(m.group(1))
    pp = data.get("props", {}).get("pageProps", {})
    jobs = [parse_job(j) for j in pp.get("jobs", [])]
    total = str(pp.get("resultCount", ""))
    cursors = pp.get("pageCursors", {}) or {}
    return jobs, total, cursors


def scrape_page(url: str):
    resp = session.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    return extract(resp.text)


def scrape_jobs(query: str = "", location: str = "usa", pages: int = 3):
    """Reusable entry point. Returns (jobs, total_estimate)."""
    all_jobs, seen, total_est, cursor = [], set(), "", ""
    for page in range(1, max(1, pages) + 1):
        url = build_url(query, location, cursor)
        jobs, total, cursors = scrape_page(url)
        if not jobs:
            break
        total_est = total or total_est
        for j in jobs:
            key = j["url"] or (j["title"], j["company"], j["location"])
            if key in seen:
                continue
            seen.add(key)
            all_jobs.append(j)
        cursor = cursors.get(str(page + 1), "")
        if page < pages and not cursor:
            break
        if page < pages:
            time.sleep(REQUEST_DELAY)
    return all_jobs, total_est


# ── Output ───────────────────────────────────────────────────────────────────

def save_json(jobs, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)


def save_csv(jobs, path):
    if not jobs:
        return
    keys = list(jobs[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(jobs)


def save_markdown(jobs, path, query, location):
    lines = [
        f"# SimplyHired Jobs — \"{query or 'all'}\" in {location}",
        f"_Scraped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · {len(jobs)} jobs_\n",
    ]
    for i, j in enumerate(jobs, 1):
        lines += [
            f"## {i}. {j['title']}",
            f"- **Company:** {j['company']}" + (f" (★ {j['rating']})" if j['rating'] else ""),
            f"- **Location:** {j['location']}",
            f"- **Salary:** {j['salary']}",
            f"- **Type:** {j['job_types'] or 'N/A'}"
            + (f" · Remote: {j['remote']}" if j['remote'] else ""),
            f"- **Posted:** {j['date_posted'] or 'N/A'}",
            f"- **Snippet:** {j['snippet']}",
            f"- **Link:** {j['url']}",
            "",
        ]
    open(path, "w", encoding="utf-8").write("\n".join(lines))


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="SimplyHired job scraper")
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("location", nargs="?", default="usa")
    ap.add_argument("pages", nargs="?", type=int, default=3)
    args = ap.parse_args()

    all_jobs = []
    seen = set()
    total_est = ""
    cursor = ""

    for page in range(1, args.pages + 1):
        url = build_url(args.query, args.location, cursor)
        print(f"  Page {page}: {url}")
        try:
            jobs, total, cursors = scrape_page(url)
        except Exception as e:
            print(f"    Error: {e}")
            break
        if not jobs:
            print("    No jobs — stopping.")
            break
        total_est = total or total_est
        new = 0
        for j in jobs:
            key = j["url"] or (j["title"], j["company"], j["location"])
            if key in seen:
                continue
            seen.add(key)
            all_jobs.append(j)
            new += 1
        print(f"    -> {new} new jobs (total available: {total})")

        # advance cursor to next page
        cursor = cursors.get(str(page + 1), "")
        if page < args.pages and not cursor:
            print("    No further pages.")
            break
        if page < args.pages:
            time.sleep(REQUEST_DELAY)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = (args.query or "all").replace(" ", "-")[:30]
    loc = args.location.replace(" ", "-").replace(",", "")[:20]
    base = f"simplyhired_{slug}_{loc}_{ts}"
    save_json(all_jobs, f"{base}.json")
    save_csv(all_jobs, f"{base}.csv")
    save_markdown(all_jobs, f"{base}.md", args.query, args.location)

    print(f"\nTotal: {len(all_jobs)} unique jobs (est. {total_est} available)")
    print(f"Saved: {base}.json / .csv / .md")


if __name__ == "__main__":
    main()
