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


def main():
    with open(os.path.join(ROOT, "data", "otel-people.json"), encoding="utf-8") as f:
        data = json.load(f)
    data["generated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data["currentMonth"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")
    data["activity"] = activity()
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
