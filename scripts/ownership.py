"""Ownership Check: five plain-language questions per component, answered by fixed rules.

Reads what the daily build already has:
  .cache/repos/<repo>/components/<path>/metadata.yaml   the part's details file
  .cache/repos/<repo>/.github/CODEOWNERS                 the review list
  .cache/repos/<repo>/CONTRIBUTING.md                    the project's written rules
  .cache/repos/<repo>/meta.json                          default branch and commit
  data/otel-people.json                                  which repos have components
  data/activity/components.csv                           open issues / PRs per component
  data/activity/merged_prs.csv (+ _state.json)           who approved and merged PRs

Writes data/ownership.json. No language model is involved: every answer comes from a
rule below, and every answer carries the files it was based on and the date it was
checked.

Answers are "Yes", "No", "Not sure" or "Not checked":
  Not sure    = we looked, but the evidence is unclear or conflicting
  Not checked = we did not or could not look (missing file, stale data, rule doesn't apply)
"Not checked" is never shown as "No".

The recent-review question never answers "No": not finding approvals in our data does
not prove that someone has stopped looking after a part.
"""
import csv
import datetime as dt
import json
import os
import sys
import urllib.parse

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
DATA = os.path.join(ROOT, "data")
ACT = os.path.join(DATA, "activity")
OUT = os.path.join(DATA, "ownership.json")

RULES_VERSION = 1
ACTIVE_DAYS = 180       # question 2: look for approvals or merges in this many days
WAIT_DAYS = 30          # question 5: a change open longer than this counts as a long wait
STALE_DAYS = 3          # snapshots older than this are treated as "Not checked"
# Parts that people install and configure directly. Other labelled paths (cmd, pkg,
# internal, tools) are shared or internal code that the default review team covers.
USER_FACING = {"receiver", "exporter", "processor", "extension", "connector", "scraper", "provider"}
WAITING_LABEL = "waiting-for-code-owners"

YES, NO, NOT_SURE, NOT_CHECKED = "Yes", "No", "Not sure", "Not checked"
OK, ATTENTION, INFO, UNKNOWN = "ok", "attention", "info", "unknown"
PROJECT_RULE, OUR_RULE = "project", "whoswho"

QUESTIONS = {
    "has_owner": "Does this part have at least one person responsible for it?",
    "recent_review": "Have the people responsible approved or merged changes in this repository recently?",
    "lists_agree": "Do the project's lists of responsible people agree with each other?",
    "seeking_help": "Is this part looking for more helpers?",
    "long_wait": "Has a change been waiting more than 30 days for the people responsible?",
}
CONTRIBUTING_ANCHORS = {
    "responsibility": "A Code Owner is responsible for a component",
    "become": "### Becoming a Code Owner",
    "emeritus": "#### Code Owners",
    "unmaintained": "unmaintained stability status",
}


# ---------- sources ----------
def read(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def blob_url(repo, ref, path, line=None):
    url = f"https://github.com/{repo}/blob/{ref}/{path}"
    return url + (f"#L{line}" if line else "")


def line_of(text, needle):
    """1-based line number of the first line containing needle, or None."""
    if not text:
        return None
    for i, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return i
    return None


def parse_codeowners(text):
    """{path: {"line", "users", "teams", "unmaintained"}} for every rule, last one wins.

    "unmaintained" is True for rows between the generator's
    "# Start unmaintained components list" / "# End ..." markers."""
    rules, section = {}, None
    for i, line in enumerate((text or "").splitlines(), 1):
        s = line.strip()
        low = s.lower()
        if low.startswith("# start unmaintained"):
            section = "unmaintained"
        elif low.startswith("# end unmaintained"):
            section = None
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        owners = [o.lstrip("@") for o in parts[1:] if o.startswith("@")]
        rules[parts[0].strip("/") or "*"] = {
            "line": i,
            "owners": owners,
            "users": [o for o in owners if "/" not in o],
            "teams": [o.split("/", 1)[1] for o in owners if "/" in o],
            "unmaintained": section == "unmaintained",
        }
    return rules


def metadata_view(text):
    """The parts of metadata.yaml the rules use, or None when it can't be read."""
    try:
        m = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(m, dict):
        return None
    status = m.get("status") or {}
    co = status.get("codeowners") or {}
    stab = status.get("stability") or {}
    levels = sorted(stab.keys()) if isinstance(stab, dict) else []
    return {
        "class": status.get("class"),
        "active": [str(u) for u in co.get("active") or []],
        "emeritus": [str(u) for u in co.get("emeritus") or []],
        "seeking_new": bool(co.get("seeking_new")),
        "unmaintained": "unmaintained" in levels,
        "codeowners_line": line_of(text, "codeowners:"),
        "stability_line": line_of(text, "stability:"),
    }


def effective_rule(rules, path):
    """The review-list line GitHub applies to path: its own line, else the nearest
    parent directory's line. The catch-all "*" line is ignored. Returns (rule, path)."""
    parts = path.strip("/").split("/")
    for n in range(len(parts), 0, -1):
        key = "/".join(parts[:n])
        if key in rules:
            return rules[key], key
    return None, None


def specific_owners(rule, rules):
    """Owners on a line minus those every line gets from the catch-all "*" rule
    (the generator adds the approvers team to every component line)."""
    default = lower_set((rules.get("*") or {}).get("owners") or [])
    return [o for o in (rule or {}).get("owners") or [] if o.lower() not in default]


def lower_set(xs):
    return {x.lower() for x in xs}


def handles(xs):
    return ", ".join("@" + x for x in xs)


# ---------- answers ----------
def answer(qid, value, status, summary, *, wrong=None, why=None, fix=None, fix_link=None, basis, evidence, checked,
           draft=None):
    """fix_link: {"label", "url"} shown after the fix text, so plain text never holds raw URLs."""
    return {"id": qid, "question": QUESTIONS[qid], "answer": value, "status": status, "summary": summary,
            "wrong": wrong, "why": why, "fix": fix, "fixLink": fix_link, "basis": basis, "evidence": evidence,
            "checked": checked, "draft": draft}


def project_basis(ctx, key, text):
    line = ctx["contributing_lines"].get(key)
    if ctx.get("contributing_file") is None:
        return {"kind": OUR_RULE, "text": text, "url": None}
    return {"kind": PROJECT_RULE, "text": text,
            "url": blob_url(ctx["repo"], ctx["ref"], ctx["contributing_file"], line)}


def our_basis(text):
    return {"kind": OUR_RULE, "text": text, "url": "https://github.com/Abhimanyu9988/otel-whos-who/blob/main/docs/ownership-check.md"}


def ev_metadata(ctx, c, line_key="codeowners_line"):
    md = c.get("metadata") or {}
    return {"label": f"Details file: {c['path']}/metadata.yaml",
            "url": blob_url(ctx["repo"], ctx["ref"], f"{c['path']}/metadata.yaml", md.get(line_key))}


def ev_codeowners(ctx, c):
    rule = c.get("codeowners_rule")
    return {"label": f"Review list: {ctx['codeowners_file']}" + (f" (line {rule['line']})" if rule else ""),
            "url": blob_url(ctx["repo"], ctx["ref"], ctx["codeowners_file"], rule["line"] if rule else None)}


def q_has_owner(ctx, c, checked):
    md, rule = c.get("metadata"), c.get("codeowners_rule")
    basis = project_basis(ctx, "responsibility",
                          "The project's contributing guide says a code owner is responsible for a component: "
                          "maintaining it, triaging and answering issues, and reviewing changes.")
    if c.get("metadata_error"):
        return answer("has_owner", NOT_CHECKED, UNKNOWN,
                      "We couldn't read this part's details file, so we didn't check.",
                      basis=basis, evidence=[ev_metadata(ctx, c)], checked=checked)
    if md is None:
        users = (rule or {}).get("users") or []
        ev = [ev_codeowners(ctx, c)] if ctx.get("codeowners_file") else []
        if users:
            return answer("has_owner", YES, OK,
                          f"The review list names {handles(users)}. This part has no details file, so we used the review list.",
                          basis=basis, evidence=ev, checked=checked)
        return answer("has_owner", NOT_SURE, UNKNOWN,
                      "We couldn't find this part's details file, and the review list names nobody specific for it.",
                      fix="Check whether this part still exists or has moved.", basis=basis, evidence=ev, checked=checked)
    active = md["active"]
    ev = [ev_metadata(ctx, c)]
    if active:
        return answer("has_owner", YES, OK, f"{len(active)} listed: {handles(active)}.",
                      basis=basis, evidence=ev, checked=checked)
    become = {"label": "How to become a code owner",
              "url": blob_url(ctx["repo"], ctx["ref"], ctx["contributing_file"], ctx["contributing_lines"].get("become"))} \
        if ctx.get("contributing_file") else None
    if md["unmaintained"]:
        ev.append(ev_metadata(ctx, c, "stability_line"))
        return answer("has_owner", NO, INFO,
                      "No one is listed, and the project has already marked this part as unmaintained.",
                      wrong="Nobody is responsible for this part right now.",
                      why="The project knows: unmaintained parts can be removed if no one steps up.",
                      fix="If you rely on it, you can volunteer to become a code owner.", fix_link=become,
                      basis=project_basis(ctx, "unmaintained",
                                          "The contributing guide says unmaintained parts move all owners to emeritus "
                                          "and are open for new code owners."),
                      evidence=ev, checked=checked)
    parent, parent_path = effective_rule(ctx["codeowners"], c["path"])
    inherited = specific_owners(parent, ctx["codeowners"]) if parent_path and parent_path != c["path"] else []
    if inherited:
        return answer("has_owner", YES, OK,
                      f"Its own details file names nobody, but the review list assigns it to the people responsible "
                      f"for {parent_path}: {handles(inherited)}.",
                      basis=basis, evidence=ev + [{"label": f"Review list: {ctx['codeowners_file']} (line {parent['line']})",
                                                    "url": blob_url(ctx["repo"], ctx["ref"], ctx["codeowners_file"],
                                                                    parent["line"])}],
                      checked=checked)
    if "/internal/" in f"/{c['path']}/":
        # A piece inside another component: name whoever the review list gives the
        # enclosing directory, for context, without claiming they review this part.
        above, above_path = effective_rule(ctx["codeowners"], c["path"].rsplit("/internal/", 1)[0])
        who = specific_owners(above, ctx["codeowners"]) if above_path else []
        context = f" The part it belongs to ({above_path}) lists {handles(who)}." if who else ""
        return answer("has_owner", NO, INFO,
                      "No one is listed by name for this internal piece; GitHub asks only the project's default "
                      "review team." + context,
                      basis=basis, evidence=ev + ([ev_codeowners(ctx, c)] if ctx.get("codeowners_file") else []),
                      checked=checked)
    if (md["class"] or "") in USER_FACING:
        return answer("has_owner", NO, ATTENTION, "No one is listed as responsible for this part.",
                      wrong="Nobody is named as responsible for this part.",
                      why="Bug reports and changes for it may wait with nobody able to review them.",
                      fix="Ask for volunteers, or volunteer yourself by adding your name to the part's details file "
                          "through the project's normal change process.", fix_link=become,
                      basis=basis, evidence=ev, checked=checked,
                      draft=draft_owner_call(ctx, c))
    return answer("has_owner", NO, INFO,
                  "No one is listed by name. This is shared or internal code, which the project's default "
                  "review team covers.",
                  basis=basis, evidence=ev + ([ev_codeowners(ctx, c)] if ctx.get("codeowners_file") else []),
                  checked=checked)


def q_recent_review(ctx, c, checked):
    md, rule = c.get("metadata"), c.get("codeowners_rule")
    listed = (md or {}).get("active") or ((rule or {}).get("users") if md is None else []) or []
    owners = [o for o in listed if "/" not in o]
    basis = our_basis(f"We look for an approval or a merge by any listed person anywhere in this repository "
                      f"in the last {ACTIVE_DAYS} days. Not finding one never counts as \"No\".")
    if listed and not owners:
        return answer("recent_review", NOT_CHECKED, UNKNOWN,
                      "Only a team is listed, and team membership isn't public, so we didn't check.",
                      basis=basis, evidence=[ev_metadata(ctx, c)] if md else [], checked=checked)
    if not owners:
        return answer("recent_review", NOT_CHECKED, UNKNOWN,
                      "Nobody is listed for this part, so there was no one to look for.",
                      basis=basis, evidence=[ev_metadata(ctx, c)] if md else [], checked=checked)
    prs = ctx.get("merged_prs")
    if not prs or not prs["rows"]:
        return answer("recent_review", NOT_CHECKED, UNKNOWN,
                      "We don't have review history for this repository yet.", basis=basis, evidence=[], checked=checked)
    since = (dt.date.fromisoformat(checked) - dt.timedelta(days=ACTIVE_DAYS)).isoformat()
    who = lower_set(owners)
    for r in prs["rows"]:  # newest first
        if r["merged_at"] < since:
            break
        people = [r["merged_by"]] + [a for a in r["approvers"].split(";") if a]
        hit = [p for p in people if p.lower() in who]
        if hit:
            url = f"https://github.com/{ctx['repo']}/pull/{r['number']}"
            return answer("recent_review", YES, OK,
                          f"Yes. The most recent we found: {handles(hit[:1])} on {r['merged_at']}.",
                          basis=basis,
                          evidence=[{"label": f"Pull request #{r['number']}, merged {r['merged_at']}", "url": url},
                                    ev_metadata(ctx, c) if md else ev_codeowners(ctx, c)],
                          checked=checked)
    covered = prs["done"] and prs["oldest"] <= since
    if not covered:
        return answer("recent_review", NOT_CHECKED, UNKNOWN,
                      f"Our review history doesn't cover the full last {ACTIVE_DAYS} days yet, so we didn't decide.",
                      basis=basis, evidence=[], checked=checked)
    emeritus = project_basis(ctx, "emeritus", "The contributing guide describes how inactive code owners are "
                                              "contacted before anything changes.")
    return answer("recent_review", NOT_SURE, UNKNOWN,
                  f"We found no approvals or merges by the people listed, anywhere in this repository, in the last "
                  f"{ACTIVE_DAYS} days.",
                  wrong="We couldn't find recent review activity from the people listed.",
                  why="This does not mean they are inactive. People also help by commenting, triaging issues, "
                      "reviewing without approving, or through other channels we don't see.",
                  fix="Nothing to change based on this alone. If you're unsure, ask in the part's issues; the project "
                      "has a written process for checking in with code owners.",
                  fix_link={"label": "The project's process", "url": emeritus["url"]} if emeritus.get("url") else None,
                  basis=basis, evidence=[ev_metadata(ctx, c) if md else ev_codeowners(ctx, c)], checked=checked)


def q_lists_agree(ctx, c, checked):
    md, rule = c.get("metadata"), c.get("codeowners_rule")
    basis = our_basis("We compare the people in the part's details file with the part's line in the review list. "
                      "In this repository the review list is generated from the details files, so they should match.")
    if md is None or not ctx.get("codeowners_file"):
        missing = "details file" if md is None else "review list"
        return answer("lists_agree", NOT_CHECKED, UNKNOWN,
                      f"We couldn't compare: this part's {missing} wasn't found.",
                      basis=basis, evidence=[ev_codeowners(ctx, c)] if ctx.get("codeowners_file") else [],
                      checked=checked)
    ev = [ev_metadata(ctx, c), ev_codeowners(ctx, c)]
    both = sorted(lower_set(md["active"]) & lower_set(md["emeritus"]))
    if both:
        return answer("lists_agree", NO, ATTENTION,
                      f"{handles(both)} {'is' if len(both) == 1 else 'are'} listed as both current and former "
                      "(emeritus) in the details file.",
                      wrong="The details file says the same person is both responsible and no longer responsible.",
                      why="People who want help can't tell who to ask, and review requests may go to the wrong person.",
                      fix="Remove the name from one of the two lists in the details file.",
                      basis=basis, evidence=ev, checked=checked, draft=draft_lists(ctx, c, both, [], []))
    expected = [] if md["unmaintained"] else md["active"]
    actual = specific_owners(rule, ctx["codeowners"])
    if rule is None and expected:
        return answer("lists_agree", NO, ATTENTION, "The review list has no line for this part.",
                      wrong="The details file names people, but the review list doesn't mention this part.",
                      why="GitHub won't ask these people to review changes to this part.",
                      fix="Regenerate the review list from the details files using the project's usual command.",
                      basis=basis, evidence=ev, checked=checked, draft=draft_lists(ctx, c, [], expected, []))
    only_md = sorted(lower_set(expected) - lower_set(actual))
    only_co = sorted(lower_set(actual) - lower_set(expected))
    if rule and rule["unmaintained"] and not md["unmaintained"]:
        return answer("lists_agree", NO, ATTENTION,
                      "The review list puts this part under \"unmaintained\", but its details file doesn't.",
                      wrong="The two files disagree about whether this part is maintained.",
                      why="Visitors and reviewers get mixed signals about whether anyone looks after it.",
                      fix="Update whichever file is out of date, then regenerate the review list.",
                      basis=basis, evidence=ev, checked=checked, draft=draft_lists(ctx, c, [], only_md, only_co))
    if only_md or only_co:
        bits = []
        if only_md:
            bits.append(f"only in the details file: {handles(only_md)}")
        if only_co:
            bits.append(f"only in the review list: {handles(only_co)}")
        return answer("lists_agree", NO, ATTENTION, "The lists differ — " + "; ".join(bits) + ".",
                      wrong="The details file and the review list name different people.",
                      why="GitHub asks the people on the review list to review changes, so the wrong people may be "
                          "asked, or the right people not asked.",
                      fix="Regenerate the review list from the details files using the project's usual command.",
                      basis=basis, evidence=ev, checked=checked, draft=draft_lists(ctx, c, [], only_md, only_co))
    if md["unmaintained"]:
        return answer("lists_agree", YES, OK,
                      "Both files agree: the part is unmaintained and nobody is listed by name.",
                      basis=basis, evidence=ev, checked=checked)
    return answer("lists_agree", YES, OK,
                  f"Both files list the same {len(expected)} " + ("person." if len(expected) == 1 else "people.")
                  if expected else "Both files list nobody by name.",
                  basis=basis, evidence=ev, checked=checked)


def q_seeking_help(ctx, c, checked):
    md, snap = c.get("metadata"), c.get("snapshot")
    basis = project_basis(ctx, "become", "The details file has a \"seeking new\" flag, and the project opens an "
                                         "\"unmaintained\" issue when it needs new code owners.")
    call = (snap or {}).get("owner_call") or ""
    if md is None and not call:
        return answer("seeking_help", NOT_CHECKED, UNKNOWN, "We couldn't find this part's details file.",
                      basis=basis, evidence=[], checked=checked)
    reasons, ev = [], []
    if md and md["seeking_new"]:
        reasons.append("its details file says it is looking for new code owners")
        ev.append(ev_metadata(ctx, c))
    if md and md["unmaintained"]:
        reasons.append("it is marked unmaintained")
        ev.append(ev_metadata(ctx, c, "stability_line"))
    if call:
        reasons.append(f"issue #{call} asks for new code owners")
        ev.append({"label": f"Issue #{call}", "url": f"https://github.com/{ctx['repo']}/issues/{call}"})
    if reasons:
        return answer("seeking_help", YES, INFO, "Yes: " + "; ".join(reasons) + ".",
                      why="This is an opportunity, not a problem: the project would welcome help here.",
                      fix="If you use this part, consider offering to help review changes or become a code owner.",
                      basis=basis, evidence=ev, checked=checked)
    return answer("seeking_help", NO, OK, "No request for new helpers was found.",
                  basis=basis, evidence=[ev_metadata(ctx, c)] if md else [], checked=checked)


def q_long_wait(ctx, c, checked):
    snap_meta = ctx.get("snapshot")
    search = (f"https://github.com/{ctx['repo']}/pulls?q=" +
              urllib.parse.quote(f'is:pr is:open label:"{WAITING_LABEL}" label:"{c["label"]}"'))
    basis = our_basis(f"We count open, non-draft pull requests that carry both this part's label and the "
                      f"project's \"{WAITING_LABEL}\" label, and look at when the oldest one was opened.")
    if not snap_meta:
        return answer("long_wait", NOT_CHECKED, UNKNOWN, "We don't have pull request data for this repository yet.",
                      basis=basis, evidence=[], checked=checked)
    age = (dt.date.fromisoformat(checked) - dt.date.fromisoformat(snap_meta["date"])).days
    if age > STALE_DAYS:
        return answer("long_wait", NOT_CHECKED, UNKNOWN,
                      f"Our pull request data is {age} days old, so we didn't decide.",
                      basis=basis, evidence=[], checked=checked)
    row = c.get("snapshot") or {}
    waiting = int(row.get("waiting_owners") or 0)
    ev = [{"label": f"Open pull requests waiting for code owners (counted {snap_meta['date']})", "url": search}]
    if waiting == 0:
        return answer("long_wait", NO, OK, "No changes are currently marked as waiting for the people responsible.",
                      basis=basis, evidence=ev, checked=checked)
    oldest = row.get("oldest_waiting") or ""
    if not oldest:
        return answer("long_wait", NOT_SURE, UNKNOWN,
                      f"{waiting} change{'s are' if waiting > 1 else ' is'} waiting, but we don't yet know for how long.",
                      basis=basis, evidence=ev, checked=checked)
    days = (dt.date.fromisoformat(checked) - dt.date.fromisoformat(oldest)).days
    if days > WAIT_DAYS:
        return answer("long_wait", YES, ATTENTION,
                      f"{waiting} change{'s are' if waiting > 1 else ' is'} waiting; the oldest was opened on "
                      f"{oldest} ({days} days ago).",
                      wrong="A change has been open for over a month and is marked as waiting for the people responsible.",
                      why="Contributors may give up, and fixes don't reach users.",
                      fix="If you're responsible for this part, please take a look. If you can't, say so on the pull "
                          "request so someone else can step in.",
                      basis=basis, evidence=ev, checked=checked)
    return answer("long_wait", NO, OK,
                  f"{waiting} change{'s are' if waiting > 1 else ' is'} waiting, all opened in the last {WAIT_DAYS} days.",
                  basis=basis, evidence=ev, checked=checked)


CHECKS = (q_has_owner, q_recent_review, q_lists_agree, q_seeking_help, q_long_wait)


# ---------- drafts (templates, never posted for you) ----------
def draft_owner_call(ctx, c):
    return (f"Title: Looking for code owners for {c['label']}\n\n"
            f"The details file for `{c['path']}` lists no active code owners "
            f"({blob_url(ctx['repo'], ctx['ref'], c['path'] + '/metadata.yaml')}).\n\n"
            "Is anyone using this component who could help review changes and answer issues? "
            "The contributing guide explains how to become a code owner.\n\n"
            "(Drafted from a template by the Who's Who Ownership Check. Please check the project's "
            "contribution rules before posting.)")


def draft_lists(ctx, c, both, only_md, only_co):
    lines = [f"Title: Code owner lists disagree for {c['label']}", "",
             f"`{c['path']}/metadata.yaml` and `{ctx['codeowners_file']}` don't match:"]
    if both:
        lines.append(f"- listed as both active and emeritus in metadata.yaml: {handles(both)}")
    if only_md:
        lines.append(f"- only in metadata.yaml: {handles(only_md)}")
    if only_co:
        lines.append(f"- only in {ctx['codeowners_file']}: {handles(only_co)}")
    lines += ["", "Suggested fix: update metadata.yaml if needed, then run `make update-codeowners` to regenerate "
                  "the review list.", "",
              "(Drafted from a template by the Who's Who Ownership Check. Please check the project's "
              "contribution rules before posting.)"]
    return "\n".join(lines)


# ---------- evaluation ----------
def evaluate(ctx, comp, checked):
    answers = [check(ctx, comp, checked) for check in CHECKS]
    summary = {s: sum(1 for a in answers if a["status"] == s) for s in (OK, ATTENTION, INFO, UNKNOWN)}
    md = comp.get("metadata") or {}
    return {"repo": ctx["repo"], "path": comp["path"], "label": comp["label"], "class": md.get("class"),
            "unmaintained": bool(md.get("unmaintained")), "summary": summary, "answers": answers}


def load_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_activity(repo):
    """Component snapshot rows by label, the snapshot's date, and merged PRs (newest first)."""
    snap = [r for r in load_csv(os.path.join(ACT, "components.csv")) if r["repo"] == repo]
    rows = sorted((r for r in load_csv(os.path.join(ACT, "merged_prs.csv")) if r["repo"] == repo),
                  key=lambda r: (r["merged_at"], int(r["number"])), reverse=True)
    state_path = os.path.join(ACT, "merged_prs_state.json")
    state = json.loads(read(state_path)) if os.path.exists(state_path) else {}
    merged = {"rows": rows, "done": bool((state.get(repo) or {}).get("done")),
              "oldest": min((r["merged_at"] for r in rows), default="9999")}
    snapshot = {"date": max(r["date"] for r in snap)} if snap else None
    return {r["label"]: r for r in snap}, snapshot, merged


def repo_context(repo, cache_dir):
    meta = json.loads(read(os.path.join(cache_dir, "meta.json")))
    files = meta.get("files") or []
    ctx = {"repo": repo, "branch": meta.get("branch") or "main", "sha": meta.get("sha"),
           "ref": meta.get("sha") or meta.get("branch") or "main",
           "codeowners_file": None, "codeowners": {}, "contributing_file": None, "contributing_lines": {}}
    for f in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        if f in files:
            ctx["codeowners_file"] = f
            ctx["codeowners"] = parse_codeowners(read(os.path.join(cache_dir, f)))
            break
    for f in ("CONTRIBUTING.md", "docs/CONTRIBUTING.md"):
        if f in files:
            text = read(os.path.join(cache_dir, f))
            ctx["contributing_file"] = f
            ctx["contributing_lines"] = {k: line_of(text, v) for k, v in CONTRIBUTING_ANCHORS.items()}
            break
    return ctx


def components_in(cache_dir):
    path = os.path.join(cache_dir, ".github", "component_labels.txt")
    if not os.path.exists(path):
        return []
    out = []
    for line in read(path).splitlines():
        parts = line.split()
        if len(parts) >= 2 and not line.lstrip().startswith("#"):
            out.append({"path": parts[0].strip("/"), "label": parts[1]})
    return out


def check_repo(repo, cache_dir, checked, activity=None):
    ctx = repo_context(repo, cache_dir)
    labels, snapshot, merged = activity if activity is not None else load_activity(repo)
    ctx["snapshot"], ctx["merged_prs"] = snapshot, merged
    results = []
    for comp in components_in(cache_dir):
        meta_path = os.path.join(cache_dir, "components", comp["path"], "metadata.yaml")
        comp["metadata"] = comp["metadata_error"] = None
        if os.path.exists(meta_path):
            comp["metadata"] = metadata_view(read(meta_path))
            comp["metadata_error"] = comp["metadata"] is None
        comp["codeowners_rule"] = ctx["codeowners"].get(comp["path"])
        comp["snapshot"] = labels.get(comp["label"])
        results.append(evaluate(ctx, comp, checked))
    return ctx, results


def main(checked=None):
    checked = checked or dt.datetime.now(dt.timezone.utc).date().isoformat()
    people = os.path.join(DATA, "otel-people.json")
    if not os.path.exists(people):
        sys.exit("data/otel-people.json is missing; run build.py first")
    repos = [r["repo"] for r in json.loads(read(people))["repos"] if r.get("components")]
    out = {"rulesVersion": RULES_VERSION, "checked": checked, "questions": QUESTIONS,
           "repos": {}, "components": []}
    for repo in repos:
        cache_dir = os.path.join(CACHE, "repos", repo.replace("/", "_"))
        if not os.path.isdir(cache_dir):
            print(f"ownership: no cached files for {repo}; skipped")
            continue
        ctx, results = check_repo(repo, cache_dir, checked)
        out["repos"][repo] = {"branch": ctx["branch"], "sha": ctx["sha"], "codeownersFile": ctx["codeowners_file"],
                              "contributingFile": ctx["contributing_file"]}
        out["components"] += results
    totals = {s: sum(c["summary"][s] for c in out["components"]) for s in (OK, ATTENTION, INFO, UNKNOWN)}
    out["totals"] = dict(totals, components=len(out["components"]))
    with open(OUT, "w", encoding="utf-8") as f:
        # One component per line: small enough to commit daily, and git diffs show
        # exactly which components' answers changed (the history of findings).
        f.write("{\n")
        for k in sorted(k for k in out if k != "components"):
            f.write(f"{json.dumps(k)}: {json.dumps(out[k], ensure_ascii=False, sort_keys=True)},\n")
        f.write('"components": [\n')
        f.write(",\n".join(json.dumps(c, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                            for c in out["components"]))
        f.write("\n]\n}")
        f.write("\n")
    print(f"ownership: {len(out['components'])} components checked; "
          f"{totals[ATTENTION]} answers need attention, {totals[UNKNOWN]} not sure / not checked")


if __name__ == "__main__":
    main()
