"""Parse the files in .cache/ into data/otel-people.json."""
import json
import os
import re

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
OUT = os.path.join(ROOT, "data", "otel-people.json")

LINK = re.compile(r"\[([^\]]+)\]\(https?://github\.com/([A-Za-z0-9-]+)/?\)")
HEAD = re.compile(r"^(#{2,5})\s+(.*)$")
SKIP = re.compile(r"become|release instructions|how to|nominat|responsibilit|guidelines|process", re.I)
TEAM = re.compile(r"@?open-telemetry/([a-z0-9-]+)")
EMER_ROLE = re.compile(r"\b(maintainer|approver|triager)s?\b", re.I)
ROLES = ("maintainer", "approver", "triager", "emeritus")


def read(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


# ---------- SIGs ----------
def load_sigs():
    ws = yaml.safe_load(read(os.path.join(CACHE, "community", "workstreams.yml")))
    items = ws if isinstance(ws, list) else ws.get("workstreams", [])
    sigs, repo_sig = [], {}
    for w in items:
        sig = {"id": w.get("id"), "name": re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", w.get("name") or ""), "category": w.get("sigCategory"),
               "parent": w.get("parent"), "repos": [], "slack": None, "meeting": None,
               "notes": None, "tcSponsors": [], "gcLiaison": None, "roadmap": None}
        for p in w.get("people") or []:
            if "gcLiaison" in p:
                sig["gcLiaison"] = p["gcLiaison"]
            if "tcSponsor" in p:
                t = p["tcSponsor"]
                sig["tcSponsors"].append({"user": t.get("username"), "level": t.get("level")}
                                         if isinstance(t, dict) else {"user": t})
        for r in w.get("resources") or []:
            if "repository" in r:
                sig["repos"].append(r["repository"])
                repo_sig.setdefault(r["repository"], []).append(sig["id"])
            elif "slack" in r:
                sig["slack"] = {"name": r["slack"].get("name"), "id": r["slack"].get("id")}
            elif "meeting" in r and not sig["meeting"]:
                m = r["meeting"]
                sig["meeting"] = m.get("schedule")
                if m.get("gDocNotes"):
                    sig["notes"] = "https://docs.google.com/document/d/" + m["gDocNotes"]
            elif "roadmapProject" in r:
                sig["roadmap"] = "https://github.com/orgs/open-telemetry/projects/%s" % r["roadmapProject"]
        sigs.append(sig)
    return sigs, repo_sig


# ---------- committees ----------
def load_committees():
    committees, cur = [], None
    for line in read(os.path.join(CACHE, "community", "community-members.md")).splitlines():
        h = re.match(r"^##\s+(.*)", line)
        if h:
            cur = {"name": h.group(1).strip(), "members": []}
            committees.append(cur)
            continue
        if cur and re.match(r"^\s*emeritus\s*:?\s*$", line, re.I) and not cur["name"].lower().endswith("emeritus"):
            cur = {"name": cur["name"] + " Emeritus", "members": []}
            committees.append(cur)
            continue
        if cur and re.match(r"^\s*[-*]\s", line):
            m = LINK.search(line)
            if m:
                rest = line[m.end():].strip(" ,")
                company, term = rest, None
                t = re.search(r",?\s*until\s+(.*)$", rest)
                if t:
                    term, company = t.group(1), rest[:t.start()].strip(" ,")
                cur["members"].append({"name": m.group(1), "user": m.group(2),
                                       "company": company or None, "termEnd": term})
    return [c for c in committees if c["members"]]


# ---------- per-repo roles ----------
def classify(text):
    t = text.lower()
    if SKIP.search(t):
        return None
    if "emeritus" in t:
        return "emeritus"
    found = [r for r in ("maintainer", "approver", "triager") if r in t]
    return found[0] if len(found) == 1 else None  # "Approvers and Maintainers" is a container


def parse_roles(md):
    out = {r: [] for r in ROLES}
    teams, role, level, in_code = {}, None, 99, False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        h = HEAD.match(line)
        if h:
            lv, text = len(h.group(1)), h.group(2)
            r = classify(text)
            if r:
                role, level = r, lv
                tm = TEAM.search(text)
                if tm:
                    teams.setdefault(r, tm.group(1))
            elif role and lv <= level:
                role = None
            continue
        if not role:
            continue
        if re.match(r"^\s*[-*]\s", line):
            m = LINK.search(line)
            if not m or m.group(2).lower() == "open-telemetry":
                continue
            rest = line[m.end():].strip(" ,.")
            entry = {"name": m.group(1).strip(), "user": m.group(2)}
            if role == "emeritus":
                was = sorted({x.lower() for x in EMER_ROLE.findall(rest)})
                entry["was"] = was or None
                entry["company"] = EMER_ROLE.sub("", rest).strip(" ,/-") or None
            else:
                entry["company"] = rest or None
            if not any(e["user"].lower() == entry["user"].lower() for e in out[role]):
                out[role].append(entry)
        else:
            tm = TEAM.search(line)
            if tm and role != "emeritus" and "github.com/orgs" in line:
                teams.setdefault(role, tm.group(1))
    return out, teams


def parse_codeowners(txt):
    rules = []
    for line in txt.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        owners = [o.lstrip("@") for o in parts[1:] if o.startswith("@")]
        if owners:
            rules.append({"path": parts[0],
                          "teams": [o.split("/", 1)[1] for o in owners if "/" in o],
                          "users": [o for o in owners if "/" not in o]})
    return rules


def parse_component_owners(txt):
    comps = (yaml.safe_load(txt) or {}).get("components") or {}
    return [{"path": k,
             "teams": [x.split("/", 1)[1] for x in (v or []) if "/" in x],
             "users": [x for x in (v or []) if "/" not in x]} for k, v in comps.items()]


def active_count(roles):
    return sum(len(v) for k, v in roles.items() if k != "emeritus")


def load_repos(repo_sig):
    base = os.path.join(CACHE, "repos")
    listing_path = os.path.join(CACHE, "org-repos.json")
    listing = json.load(open(listing_path)) if os.path.exists(listing_path) else {}
    repos = []
    for dname in sorted(os.listdir(base)):
        d = os.path.join(base, dname)
        meta = json.load(open(os.path.join(d, "meta.json")))
        full = dname.replace("_", "/", 1)
        files = meta["files"]
        e = {"repo": full, "sigs": repo_sig.get(full, []), "branch": meta["branch"],
             "description": listing.get(full, {}).get("description") or None,
             "roles": None, "rolesSource": None, "teams": {}, "codeowners": [], "componentOwners": []}
        best = None
        for f in ("README.md", "CONTRIBUTING.md", "docs/README.md", "docs/CONTRIBUTING.md"):
            if f in files:
                roles, teams = parse_roles(read(os.path.join(d, f)))
                n = active_count(roles)
                if n and (best is None or n > best[0]):
                    best = (n, roles, teams, f)
        if best:
            _, e["roles"], e["teams"], e["rolesSource"] = best
        for f in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
            if f in files:
                e["codeowners"], e["codeownersFile"] = parse_codeowners(read(os.path.join(d, f))), f
                break
        for f in (".github/component_owners.yml", ".github/component-owners.yml"):
            if f in files:
                e["componentOwners"], e["componentOwnersFile"] = parse_component_owners(read(os.path.join(d, f))), f
                break
        repos.append(e)

    # JS keeps one role list for both JS repos; "Contrib Triagers" applies to js-contrib only.
    by = {r["repo"]: r for r in repos}
    js, jsc = by.get("open-telemetry/opentelemetry-js"), by.get("open-telemetry/opentelemetry-js-contrib")
    if js and jsc and js["roles"] and not (jsc["roles"] and active_count(jsc["roles"])):
        md = read(os.path.join(base, "open-telemetry_opentelemetry-js", js["rolesSource"]))
        sec = re.search(r"^### Contrib Triagers\s*$(.*?)^#{2,3} ", md, re.S | re.M)
        contrib = {m.group(2).lower() for m in LINK.finditer(sec.group(1))} if sec else set()
        ct = [x for x in js["roles"]["triager"] if x["user"].lower() in contrib]
        js["roles"]["triager"] = [x for x in js["roles"]["triager"] if x["user"].lower() not in contrib]
        jsc["roles"] = {"maintainer": list(js["roles"]["maintainer"]), "approver": list(js["roles"]["approver"]),
                        "triager": ct, "emeritus": []}
        jsc["rolesSource"], jsc["sharedFrom"] = None, js["repo"]

    # repos with no SIG and nothing to show add noise
    return [r for r in repos if r["sigs"] or (r["roles"] and active_count(r["roles"]))
            or any(x["users"] for x in r["codeowners"] + r["componentOwners"])], bool(listing)


def main():
    sigs, repo_sig = load_sigs()
    people = yaml.safe_load(read(os.path.join(CACHE, "community", "people.yml")))
    repos, org_wide = load_repos(repo_sig)
    data = {
        "orgWide": org_wide,
        "sigs": sigs,
        "committees": load_committees(),
        "repos": repos,
        "peopleMeta": {k: {"name": v.get("name"), "company": v.get("company")}
                       for k, v in (people.get("people") or {}).items()},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    print(f"{len(sigs)} SIGs, {len(repos)} repos "
          f"({sum(1 for r in repos if not r['sigs'])} without a SIG), "
          f"{sum(1 for r in repos if r['roles'] and active_count(r['roles']))} with role lists")


if __name__ == "__main__":
    main()
