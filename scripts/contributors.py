"""Collect merged PRs (who wrote, merged and approved them) for every repo.

Writes data/activity/merged_prs.csv:
    repo,number,merged_at,author,merged_by,approvers
One row per merged PR in the last CONTRIB_DAYS days (default 365). approvers is a
";"-joined list of people who left an approving review, excluding the author.
Bot accounts keep a "[bot]" suffix so the page can leave them out.

PRs are read newest-updated first, which means every run only has to read until it
reaches what the previous run already saw. The first run backfills the window in
chunks of CONTRIB_MAX_PAGES pages per run; progress is kept in
data/activity/merged_prs_state.json, so a backfill that runs out of budget or
hits the rate limit picks up where it stopped on the next run.

Needs GITHUB_TOKEN. Without one it exits without changing anything.
"""
import datetime as dt
import json
import os
import sys
import time

from activity import TOKEN, RateLimited, graphql, read_csv, warn, write_csv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "activity", "merged_prs.csv")
STATE = os.path.join(DATA, "activity", "merged_prs_state.json")
FIELDS = ["repo", "number", "merged_at", "author", "merged_by", "approvers"]
WINDOW_DAYS = int(os.environ.get("CONTRIB_DAYS", "365"))
MAX_PAGES = int(os.environ.get("CONTRIB_MAX_PAGES", "150"))

QUERY = """query($owner:String!, $name:String!, $after:String) {
  repository(owner:$owner, name:$name) {
    pullRequests(states:MERGED, first:50, after:$after, orderBy:{field:UPDATED_AT, direction:DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number mergedAt updatedAt
        author { login __typename }
        mergedBy { login __typename }
        reviews(states:APPROVED, first:30) { nodes { author { login __typename } } }
      }
    }
  }
}"""


def login(actor):
    if not actor or not actor.get("login"):
        return ""
    name = actor["login"]
    if actor.get("__typename") == "Bot" and not name.endswith("[bot]"):
        name += "[bot]"
    return name


def to_row(repo, n):
    author = login(n.get("author"))
    approvers = []
    for rv in ((n.get("reviews") or {}).get("nodes") or []):
        a = login(rv.get("author"))
        if a and a != author and a not in approvers:
            approvers.append(a)
    return {"repo": repo, "number": str(n["number"]), "merged_at": n["mergedAt"][:10], "author": author,
            "merged_by": login(n.get("mergedBy")), "approvers": ";".join(approvers)}


class Budget:
    def __init__(self, pages):
        self.left = pages


def walk(repo, after, stop_before, cutoff, budget, rows):
    """Read pages from `after` until an item updated before `stop_before` (already
    seen) or `cutoff` (outside the window). Returns (finished, cursor, newest)."""
    owner, name = repo.split("/", 1)
    newest = None
    while budget.left > 0:
        data = graphql(QUERY, {"owner": owner, "name": name, "after": after})
        budget.left -= 1
        conn = ((data.get("repository") or {}).get("pullRequests")) or {}
        nodes = conn.get("nodes") or []
        stop = False
        for n in nodes:
            upd = n.get("updatedAt") or ""
            newest = newest or upd
            if upd < cutoff or (stop_before and upd < stop_before):
                stop = True
                break
            if n.get("mergedAt") and n["mergedAt"][:10] >= cutoff[:10]:
                r = to_row(repo, n)
                rows[(repo, r["number"])] = r
        page = conn.get("pageInfo") or {}
        if stop or not page.get("hasNextPage"):
            return True, None, newest
        after = page["endCursor"]
        time.sleep(0.3)
    return False, after, newest


def main():
    if not TOKEN:
        print("no GITHUB_TOKEN; skipping merged PRs")
        return
    with open(os.path.join(DATA, "otel-people.json"), encoding="utf-8") as f:
        repos = [r["repo"] for r in json.load(f)["repos"]]
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = (now - dt.timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    rows = {(r["repo"], r["number"]): r for r in read_csv(OUT) if r["merged_at"] >= cutoff[:10]}
    budget = Budget(MAX_PAGES)

    try:
        # 1. catch up on what changed since the last run (cheap: usually one page per repo)
        for repo in repos:
            st = state.get(repo) or {}
            if budget.left <= 0:
                break
            # an hour of overlap so PRs updated during the previous run are not missed
            seen = st.get("newest")
            if seen:
                seen = (dt.datetime.strptime(seen, "%Y-%m-%dT%H:%M:%SZ") - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            finished, cursor, newest = walk(repo, None, seen, cutoff, budget, rows)
            if not st:  # first sight of this repo: the head pass is the start of its backfill
                st = {"done": finished, "cursor": cursor, "newest": newest}
            elif finished:
                st["newest"] = newest or st.get("newest")
            else:  # keep the old mark so the next run reads the whole gap again
                warn(f"{repo}: catch-up stopped by the page budget")
            state[repo] = st
        # 2. continue backfills
        for repo in repos:
            st = state.get(repo) or {}
            if st.get("done") or not st.get("cursor") or budget.left <= 0:
                continue
            finished, cursor, _ = walk(repo, st["cursor"], None, cutoff, budget, rows)
            st.update({"done": finished, "cursor": cursor})
    except RateLimited as e:
        warn(f"merged PRs: rate limited ({e}); continuing next run")

    write_csv(OUT, FIELDS, list(rows.values()), lambda r: (r["merged_at"], r["repo"], int(r["number"])))
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)
        f.write("\n")
    pending = [r for r in repos if not (state.get(r) or {}).get("done")]
    print(f"merged PRs: {len(rows)} in the last {WINDOW_DAYS} days, {MAX_PAGES - budget.left} pages read, "
          f"{len(pending)} repos still backfilling")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never break the directory build
        warn(f"merged PR collection failed: {e}")
        sys.exit(0)
