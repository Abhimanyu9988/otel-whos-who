"""Count open issues and PRs per component label, for repos that have components.

Components come from data/otel-people.json (built from each repo's
.github/component_labels.txt and the components' metadata.yaml). Every open issue
and PR of those repos is listed once through GraphQL with its labels, so the
whole snapshot costs a few dozen points no matter how many components there are.

Writes:
  data/activity/components.csv        today's snapshot, one row per component label
      date,repo,label,open_issues,bugs,needs_triage,newcomer,oldest_issue,open_prs,waiting_owners,owner_call,oldest_waiting
      owner_call is the open issue labelled "unmaintained" for the component: the
      repo's call for new code owners (empty when there is none).
      oldest_waiting is the day the oldest open PR labelled waiting-for-code-owners
      was opened (when the label was added is not recorded, so this is an upper bound).
      Rows with nothing open are left out. label "_unlabelled" counts open issues
      and PRs that carry no component label.
  data/activity/components_daily.csv  date,repo,label,open_issues,open_prs
      The same counts kept over time (open counts can't be reconstructed later).

Needs GITHUB_TOKEN. Without one it exits without changing anything.
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import time

from activity import TOKEN, RateLimited, graphql, read_csv, warn, write_csv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SNAPSHOT = os.path.join(DATA, "activity", "components.csv")
DAILY = os.path.join(DATA, "activity", "components_daily.csv")
FIELDS = ["date", "repo", "label", "open_issues", "bugs", "needs_triage", "newcomer",
          "oldest_issue", "open_prs", "waiting_owners", "owner_call", "oldest_waiting"]
UNLABELLED = "_unlabelled"
NEWCOMER = {"good first issue", "help wanted"}
TITLE_COMPONENT = re.compile(r"\[([a-z0-9_]+/[a-z0-9_/]+)\]")

PAGE = """query($owner:String!, $name:String!, $after:String) {
  repository(owner:$owner, name:$name) {
    %s(states:OPEN, first:100, after:$after) {
      pageInfo { hasNextPage endCursor }
      nodes { number title createdAt %s labels(first:40) { nodes { name } } }
    }
  }
}"""


def list_open(full, kind):
    """Every open issue or PR of a repo: [{number, createdAt, labels, isDraft}]."""
    owner, name = full.split("/", 1)
    query = PAGE % (kind, "isDraft" if kind == "pullRequests" else "")
    out, after = [], None
    for _ in range(100):  # 10k items is far beyond any OTel repo
        data = graphql(query, {"owner": owner, "name": name, "after": after})
        conn = ((data.get("repository") or {}).get(kind)) or {}
        for n in conn.get("nodes") or []:
            out.append({"number": n["number"], "title": n.get("title") or "", "createdAt": n["createdAt"], "isDraft": n.get("isDraft", False),
                        "labels": {l["name"] for l in (n.get("labels") or {}).get("nodes") or []}})
        page = conn.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        after = page["endCursor"]
        time.sleep(0.5)
    return out


def count(repo, labels, issues, prs, today):
    """Per-label counts. An item with several component labels counts for each."""
    rows = {}

    def row(label):
        if label not in rows:
            rows[label] = {"date": today, "repo": repo, "label": label, "open_issues": 0, "bugs": 0,
                           "needs_triage": 0, "newcomer": 0, "oldest_issue": "", "open_prs": 0, "waiting_owners": 0,
                           "owner_call": "", "oldest_waiting": ""}
        return rows[label]

    for it in issues:
        hit = [l for l in it["labels"] if l in labels] or [UNLABELLED]
        if "unmaintained" in it["labels"]:
            # calls for owners are often filed without the component label but name
            # it in the title, e.g. "[receiver/flinkmetrics] is unmaintained"
            for l in TITLE_COMPONENT.findall(it.get("title", "")):
                if l in labels and l not in hit:
                    call = row(l)
                    if not call["owner_call"] or it["number"] < int(call["owner_call"]):
                        call["owner_call"] = str(it["number"])
        for l in hit:
            r = row(l)
            r["open_issues"] += 1
            r["bugs"] += "bug" in it["labels"]
            r["needs_triage"] += "needs triage" in it["labels"]
            r["newcomer"] += bool(NEWCOMER & it["labels"])
            if "unmaintained" in it["labels"] and l != UNLABELLED:
                if not r["owner_call"] or it["number"] < int(r["owner_call"]):
                    r["owner_call"] = str(it["number"])
            day = it["createdAt"][:10]
            if not r["oldest_issue"] or day < r["oldest_issue"]:
                r["oldest_issue"] = day
    for it in prs:
        if it["isDraft"]:
            continue
        hit = [l for l in it["labels"] if l in labels] or [UNLABELLED]
        for l in hit:
            r = row(l)
            r["open_prs"] += 1
            if "waiting-for-code-owners" in it["labels"]:
                r["waiting_owners"] += 1
                day = it["createdAt"][:10]
                if not r["oldest_waiting"] or day < r["oldest_waiting"]:
                    r["oldest_waiting"] = day
    return sorted(rows.values(), key=lambda r: r["label"])


def main():
    if not TOKEN:
        print("no GITHUB_TOKEN; skipping component counts")
        return
    with open(os.path.join(DATA, "otel-people.json"), encoding="utf-8") as f:
        repos = [r for r in json.load(f)["repos"] if r.get("components")]
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    snap = []
    for r in repos:
        try:
            issues, prs = list_open(r["repo"], "issues"), list_open(r["repo"], "pullRequests")
        except RateLimited as e:
            warn(f"component counts rate limited on {r['repo']} ({e}); keeping the previous snapshot")
            return
        labels = {c["label"] for c in r["components"]}
        rows = count(r["repo"], labels, issues, prs, today)
        snap += rows
        print(f"components: {r['repo']}: {len(issues)} open issues, {len(prs)} open PRs, {len(rows)} labels with activity")
    if not snap:
        return
    write_csv(SNAPSHOT, FIELDS, snap, lambda x: (x["repo"], x["label"]))
    hist = [x for x in read_csv(DAILY) if x["date"] != today]
    hist += [{k: x[k] for k in ("date", "repo", "label", "open_issues", "open_prs")} for x in snap]
    write_csv(DAILY, ["date", "repo", "label", "open_issues", "open_prs"], hist,
              lambda x: (x["date"], x["repo"], x["label"]))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never break the directory build
        warn(f"component counts failed: {e}")
        sys.exit(0)
