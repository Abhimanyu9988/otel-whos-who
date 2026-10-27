"""Render site/template.html + data/ into _site/index.html."""
import csv
import datetime
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACT = os.path.join(ROOT, "data", "activity")


def read_csv(name):
    path = os.path.join(ACT, name)
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(v):
    return int(v) if v not in (None, "") else None


def activity():
    """Compact per-repo series for the page: arrays aligned to sorted months / dates."""
    mrows, drows = read_csv("monthly.csv"), read_csv("daily.csv")
    months = sorted({r["month"] for r in mrows})
    mi = {m: i for i, m in enumerate(months)}
    monthly = {}
    for r in mrows:
        s = monthly.setdefault(r["repo"], [[None] * len(months) for _ in range(3)])
        for k, key in enumerate(("prs_opened", "prs_merged", "issues_opened")):
            s[k][mi[r["month"]]] = num(r[key])
    dates = sorted({r["date"] for r in drows})
    di = {d: i for i, d in enumerate(dates)}
    daily, stars = {}, {}
    for r in drows:
        s = daily.setdefault(r["repo"], [[None] * len(dates) for _ in range(2)])
        s[0][di[r["date"]]], s[1][di[r["date"]]] = num(r["open_prs"]), num(r["open_issues"])
        if r["date"] == dates[-1]:
            stars[r["repo"]] = num(r["stars"])
    return {"months": months, "monthly": monthly, "dates": dates, "daily": daily, "stars": stars}


COMP_KEYS = ("open_issues", "bugs", "needs_triage", "newcomer", "oldest_issue", "open_prs", "waiting_owners", "owner_call")


def component_counts():
    """{date, repos: {repo: {label: [open_issues, bugs, needs_triage, newcomer, oldest_issue, open_prs, waiting_owners, owner_call]}}}"""
    rows = read_csv("components.csv")
    out = {"date": max((r["date"] for r in rows), default=None), "repos": {}}
    for r in rows:
        out["repos"].setdefault(r["repo"], {})[r["label"]] = [
            r.get(k) or "" if k == "oldest_issue" else num(r.get(k)) for k in COMP_KEYS]
    return out


# Accounts that act for automation but are not GitHub Apps, so they have no [bot] suffix.
NOT_PEOPLE = {"opentelemetrybot", "otelbot", "github-actions", "renovate", "dependabot", "copilot", "k8s-ci-robot"}
WINDOWS = (30, 90, 365)


def is_person(login):
    return bool(login) and not login.endswith("[bot]") and login.lower() not in NOT_PEOPLE


def contributor_counts():
    """Per person and repo, for each window: PRs authored (merged), PRs merged, approvals given.

    Compact form for the page: users and repos as index lists, then per window rows of
    [user, repo, authored, merged, approved]."""
    rows = read_csv("merged_prs.csv")
    state_path = os.path.join(ACT, "merged_prs_state.json")
    state = json.load(open(state_path, encoding="utf-8")) if os.path.exists(state_path) else {}
    today = datetime.datetime.now(datetime.timezone.utc).date()
    users, repos, ui, ri = [], [], {}, {}

    def idx(v, lst, ix):
        if v not in ix:
            ix[v] = len(lst)
            lst.append(v)
        return ix[v]

    windows = {}
    for days in WINDOWS:
        start = (today - datetime.timedelta(days=days)).isoformat()
        agg = {}
        for r in rows:
            if r["merged_at"] < start:
                continue
            rk = idx(r["repo"], repos, ri)

            def bump(user, k):
                if is_person(user):
                    cell = agg.setdefault((idx(user, users, ui), rk), [0, 0, 0])
                    cell[k] += 1

            bump(r["author"], 0)
            bump(r["merged_by"], 1)
            for a in filter(None, r["approvers"].split(";")):
                bump(a, 2)
        windows[str(days)] = [[u, rk, *c] for (u, rk), c in agg.items()]
    return {"users": users, "repos": repos, "windows": windows,
            "since": min((r["merged_at"] for r in rows), default=None),
            "backfilling": sorted(k for k, v in state.items() if not v.get("done"))}


def main():
    with open(os.path.join(ROOT, "data", "otel-people.json"), encoding="utf-8") as f:
        data = json.load(f)
    data["generated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data["currentMonth"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")
    data["activity"] = activity()
    data["componentCounts"] = component_counts()
    data["contributors"] = contributor_counts()
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    with open(os.path.join(ROOT, "site", "template.html"), encoding="utf-8") as f:
        html = f.read().replace("__DATA__", blob)
    out = os.path.join(ROOT, "_site")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    shutil.copy(os.path.join(ROOT, "data", "otel-people.json"), os.path.join(out, "otel-people.json"))
    if os.path.isdir(ACT):
        shutil.copytree(ACT, os.path.join(out, "activity"), dirs_exist_ok=True)
    print("wrote _site/index.html", len(html), "bytes")


if __name__ == "__main__":
    main()
