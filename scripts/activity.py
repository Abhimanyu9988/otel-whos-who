"""Collect PR and issue activity for every repo in data/otel-people.json.

Writes two append-friendly CSVs (committed, so history accumulates):

  data/activity/monthly.csv  month,repo,prs_opened,prs_merged,issues_opened
      One row per repo per calendar month. The current and previous month are
      recomputed on every run; older months are filled once (backfill), newest
      first, a bounded number of queries per run so rate limits are respected.

  data/activity/daily.csv    date,repo,open_prs,open_issues,stars
      A snapshot of open counts, one row per repo per day. Open counts cannot
      be reconstructed for the past, so this history starts on the first run.

Needs GITHUB_TOKEN (GraphQL). Without one it exits without changing anything.
"""
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
ACT = os.path.join(DATA, "activity")
MONTHLY = os.path.join(ACT, "monthly.csv")
DAILY = os.path.join(ACT, "daily.csv")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
MONTHS_BACK = int(os.environ.get("ACTIVITY_MONTHS", "12"))      # full months kept besides the current one
MAX_QUERIES = int(os.environ.get("ACTIVITY_MAX_QUERIES", "70"))  # GraphQL calls per run
CELLS_PER_QUERY = 10                                             # x3 search aliases each
METRICS = ("prs_opened", "prs_merged", "issues_opened")


def warn(msg):
    print("::warning::" + msg)


class RateLimited(Exception):
    pass


def graphql(query):
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body, headers={
        "Authorization": "Bearer " + TOKEN, "Content-Type": "application/json", "User-Agent": "otel-whos-who"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise RateLimited(f"HTTP {e.code}")
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
            continue
        errs = out.get("errors") or []
        if any(e.get("type") in ("RATE_LIMITED", "RATE_LIMIT") or "rate limit" in str(e.get("message", "")).lower()
               for e in errs):
            raise RateLimited(str(errs[0].get("message")))
        for e in errs:
            if e.get("type") != "NOT_FOUND":
                warn("GraphQL: " + str(e.get("message"))[:200])
        return out.get("data") or {}
    return {}


def month_list(today):
    months, y, m = [], today.year, today.month
    for _ in range(MONTHS_BACK + 1):
        months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return months  # newest first


def month_range(month, today):
    y, m = map(int, month.split("-"))
    start = dt.date(y, m, 1)
    end = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
    return start.isoformat(), min(end, today).isoformat()


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows, key):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = sorted(rows, key=key)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def q(s):
    return json.dumps(s)


def snapshot(repos, today):
    rows = []
    for i in range(0, len(repos), 25):
        chunk = repos[i:i + 25]
        parts = []
        for j, full in enumerate(chunk):
            owner, name = full.split("/", 1)
            parts.append(f'r{j}: repository(owner:{q(owner)}, name:{q(name)}) {{ '
                         f'issues(states:OPEN){{totalCount}} pullRequests(states:OPEN){{totalCount}} stargazerCount }}')
        data = graphql("query{" + " ".join(parts) + "}")
        for j, full in enumerate(chunk):
            r = data.get(f"r{j}")
            if r:
                rows.append({"date": today.isoformat(), "repo": full,
                             "open_prs": r["pullRequests"]["totalCount"],
                             "open_issues": r["issues"]["totalCount"],
                             "stars": r["stargazerCount"]})
        time.sleep(1)
    return rows


def monthly(repos, today, existing):
    months = month_list(today)
    have = {(r["month"], r["repo"]): r for r in existing if r["month"] in months}
    refresh = set(months[:2])  # current + previous month change as PRs merge
    todo = [(m, r) for m in months for r in repos if m in refresh or (m, r) not in have]
    budget, done = MAX_QUERIES, 0
    for i in range(0, len(todo), CELLS_PER_QUERY):
        if budget <= 0:
            break
        cells = todo[i:i + CELLS_PER_QUERY]
        parts = []
        for j, (m, full) in enumerate(cells):
            a, b = month_range(m, today)
            base = f"repo:{full}"
            parts.append(f'c{j}a: search(query:{q(base + " is:pr created:" + a + ".." + b)}, type:ISSUE, first:0){{issueCount}}')
            parts.append(f'c{j}b: search(query:{q(base + " is:pr is:merged merged:" + a + ".." + b)}, type:ISSUE, first:0){{issueCount}}')
            parts.append(f'c{j}c: search(query:{q(base + " is:issue created:" + a + ".." + b)}, type:ISSUE, first:0){{issueCount}}')
        try:
            data = graphql("query{" + " ".join(parts) + "}")
        except RateLimited as e:
            warn(f"rate limited after {done} cells, continuing next run ({e})")
            break
        budget -= 1
        for j, (m, full) in enumerate(cells):
            if all(f"c{j}{k}" in data for k in "abc"):
                have[(m, full)] = {"month": m, "repo": full,
                                   "prs_opened": data[f"c{j}a"]["issueCount"],
                                   "prs_merged": data[f"c{j}b"]["issueCount"],
                                   "issues_opened": data[f"c{j}c"]["issueCount"]}
                done += 1
        time.sleep(2)
    missing = sum(1 for m in months for r in repos if (m, r) not in have)
    print(f"monthly: updated {done} repo-months, {missing} still to backfill")
    return list(have.values())


def main():
    if not TOKEN:
        print("no GITHUB_TOKEN; skipping activity")
        return
    with open(os.path.join(DATA, "otel-people.json"), encoding="utf-8") as f:
        repos = [r["repo"] for r in json.load(f)["repos"]]
    today = dt.datetime.now(dt.timezone.utc).date()

    try:
        snap = snapshot(repos, today)
    except RateLimited as e:
        warn(f"snapshot rate limited ({e})")
        snap = []
    if snap:
        rows = [r for r in read_csv(DAILY) if r["date"] != today.isoformat()] + snap
        write_csv(DAILY, ["date", "repo", "open_prs", "open_issues", "stars"], rows, lambda r: (r["date"], r["repo"]))
        print(f"daily: {len(snap)} repos snapshotted")

    rows = monthly(repos, today, read_csv(MONTHLY))
    write_csv(MONTHLY, ["month", "repo", *METRICS], rows, lambda r: (r["month"], r["repo"]))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # activity must never break the directory build
        warn(f"activity collection failed: {e}")
        sys.exit(0)
