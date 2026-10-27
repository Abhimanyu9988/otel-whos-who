"""Download the public files the directory is built from into .cache/.

Sources:
  * open-telemetry/community: workstreams.yml, people.yml, community-members.md
  * every repository: README.md, CONTRIBUTING.md (or docs/ variants), CODEOWNERS,
    .github/component_owners.yml, .github/component_labels.txt
  * repos with component_labels.txt: each listed component's metadata.yaml

The repository list comes from workstreams.yml (repos assigned to a SIG). When a
GITHUB_TOKEN is set, the full list of non-archived public repos in the org is added
as well, so repos without a SIG are included too.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import yaml

ORG = "open-telemetry"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
RAW = "https://raw.githubusercontent.com"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

ROLE_FILES = ["README.md", "CONTRIBUTING.md", "docs/README.md", "docs/CONTRIBUTING.md"]
OWNER_FILES = [".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS",
               ".github/component_owners.yml", ".github/component-owners.yml"]
# Collector-style repos map each component directory to its issue label here; every
# component's metadata.yaml then gives its class, stability and code owners.
LABELS_FILE = ".github/component_labels.txt"


def label_paths(text):
    """(path, label) pairs from a component_labels.txt."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and not line.lstrip().startswith("#"):
            out.append((parts[0], parts[1]))
    return out


def get(url, api=False):
    """Return bytes, or None on 404. Retries other failures."""
    headers = {"User-Agent": "otel-whos-who"}
    if api:
        headers["Accept"] = "application/vnd.github+json"
        if TOKEN:
            headers["Authorization"] = "Bearer " + TOKEN
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == 4:
                raise
        except (urllib.error.URLError, OSError):  # includes timeouts and dropped connections
            if attempt == 4:
                raise
        time.sleep(1.5 * (attempt + 1))


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def org_repos():
    """Non-archived public repos with their default branch, via the API (needs a token)."""
    repos, page = {}, 1
    while True:
        body = get(f"https://api.github.com/orgs/{ORG}/repos?type=public&per_page=100&page={page}", api=True)
        batch = json.loads(body or b"[]")
        if not batch:
            break
        for r in batch:
            if not r.get("archived"):
                repos[r["full_name"]] = {"branch": r.get("default_branch") or "main",
                                         "description": r.get("description") or ""}
        page += 1
    return repos


def fetch_repo(full, branch):
    d = os.path.join(CACHE, "repos", full.replace("/", "_"))
    if branch is None:  # unknown default branch: find it via README
        for b in ("main", "master"):
            if get(f"{RAW}/{full}/{b}/README.md") is not None:
                branch = b
                break
        branch = branch or "main"
    meta = {"branch": branch, "files": []}
    for f in ROLE_FILES + OWNER_FILES + [LABELS_FILE]:
        data = get(f"{RAW}/{full}/{branch}/{f}")
        if data is not None:
            save(os.path.join(d, f), data)
            meta["files"].append(f)
    save(os.path.join(d, "meta.json"), json.dumps(meta).encode())
    return full, len(meta["files"])


def fetch_component_metadata(full):
    """metadata.yaml of every component listed in the repo's component_labels.txt."""
    d = os.path.join(CACHE, "repos", full.replace("/", "_"))
    labels = os.path.join(d, LABELS_FILE)
    if not os.path.exists(labels):
        return 0
    branch = json.load(open(os.path.join(d, "meta.json")))["branch"]
    with open(labels, encoding="utf-8") as f:
        paths = [p for p, _ in label_paths(f.read())]

    def one(path):
        data = get(f"{RAW}/{full}/{branch}/{path}/metadata.yaml")
        if data is not None:
            save(os.path.join(d, "components", path, "metadata.yaml"), data)
        return data is not None

    with ThreadPoolExecutor(max_workers=8) as pool:
        n = sum(pool.map(one, paths))
    print(f"{full}: metadata.yaml for {n} of {len(paths)} labelled components")
    return n


def main():
    community = os.path.join(CACHE, "community")
    for f in ("workstreams.yml", "people.yml", "community-members.md"):
        data = get(f"{RAW}/{ORG}/community/main/{f}")
        if data is None:
            sys.exit(f"missing {ORG}/community/{f}")
        save(os.path.join(community, f), data)

    ws = yaml.safe_load(open(os.path.join(community, "workstreams.yml"), encoding="utf-8"))
    items = ws if isinstance(ws, list) else ws.get("workstreams", [])
    targets = {}
    for w in items:
        for res in w.get("resources") or []:
            if "repository" in res:
                targets[res["repository"]] = None

    listing = {}
    if TOKEN:
        try:
            listing = org_repos()
        except Exception as e:  # keep going with the SIG list
            print("org listing failed, using SIG repos only:", e, file=sys.stderr)
    for full, info in listing.items():
        targets[full] = info["branch"]
    save(os.path.join(CACHE, "org-repos.json"), json.dumps(listing, indent=1).encode())

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda kv: fetch_repo(*kv), sorted(targets.items())))
    print(f"fetched {len(results)} repositories ({'org-wide' if listing else 'SIG repos only'})")
    for full, _ in results:
        fetch_component_metadata(full)


if __name__ == "__main__":
    main()
