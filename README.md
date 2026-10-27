# OpenTelemetry Who's Who

**https://abhimanyu9988.github.io/otel-whos-who/**

One searchable page with every OpenTelemetry SIG and repository, and the people who run them: maintainers, approvers, triagers, emeritus members, component code owners, Technical Committee sponsors, Governance Committee liaisons and committee members. Search a GitHub handle to see everything one person holds across the project.

The page is rebuilt every day from public sources. Nothing is entered by hand.

## Why

OpenTelemetry already publishes this information, but it is spread out:

| What | Where it lives |
|---|---|
| SIGs, meetings, Slack, repos, TC sponsors, GC liaisons | `workstreams.yml` and `people.yml` in [open-telemetry/community](https://github.com/open-telemetry/community) |
| Governance and Technical Committees | `community-members.md` in the same repo |
| Maintainers, approvers, triagers, emeritus | the role sections of each repository's `README.md` or `CONTRIBUTING.md` |
| Component code owners | each repository's `CODEOWNERS`, and `.github/component_owners.yml` in several contrib repos |

Finding who owns a Collector component, who can approve a Python contrib PR, or everything one person is responsible for means opening dozens of files. This page puts them side by side.

## Components

For repositories that publish `.github/component_labels.txt` (today, `opentelemetry-collector-contrib`), the Components tab lists every component with:

- its stability, active code owners and whether it is seeking new ones, from the component's `metadata.yaml`;
- open issues, bugs, issues needing triage, open PRs, PRs waiting on code owners and good-first/help-wanted issues, counted from its issue label once a day;
- open issues per active code owner, to show where components need more owners.

Filter by type (receivers, exporters, processors, extensions, connectors) or to components seeking owners, and click any count to open that list on GitHub.

## Contributors

Merged PRs over the last 30 days, 90 days or 12 months: PRs each person wrote, PRs they merged and PRs they approved, across all repositories or one. These are activity counts, not a ranking: triage, design, docs and meetings don't show up in them. Bots are left out. For longer history and company or country breakdowns, use [CNCF DevStats for OpenTelemetry](https://opentelemetry.devstats.cncf.io/).

## Corrections

The page only mirrors the sources above. If a name, company or role is wrong, fix it in the OpenTelemetry repository it comes from and the next daily build will pick it up. Parsing problems (a list that is missing or misread) are welcome as issues here.

## Known gaps

- Live GitHub team membership is visible only to org members, so the README lists are the public record. A README can lag behind a team change.
- Some repositories defer to another list (the Technical Committee, or the parent SIG's main repo) and show no names of their own.
- Repositories with no SIG and no role lists or code owners are left out.

## How it works

```
scripts/fetch.py         download the source files into .cache/ (org-wide when GITHUB_TOKEN is set)
scripts/build.py         parse them into data/otel-people.json
scripts/activity.py      PRs and issues per repo per month, open counts per day (data/activity/)
scripts/components.py    open issues and PRs per component label (data/activity/components*.csv)
scripts/contributors.py  merged PRs with author, merger and approvers (data/activity/merged_prs.csv)
scripts/render.py        embed the data into site/template.html -> _site/index.html
```

The three collectors need `GITHUB_TOKEN` and skip themselves without one. `contributors.py` backfills 12 months in chunks over the first few daily runs; the Contributors tab says so while it is incomplete.

`.github/workflows/update.yml` runs the three steps daily, commits `data/otel-people.json` when anything changed (so the git history doubles as a log of role changes), and deploys `_site/` to GitHub Pages.

Run it locally:

```bash
pip install -r requirements.txt
GITHUB_TOKEN=$(gh auth token) python scripts/fetch.py   # token optional; without it only SIG repos are read
python scripts/build.py
GITHUB_TOKEN=$(gh auth token) python scripts/components.py     # optional
GITHUB_TOKEN=$(gh auth token) python scripts/contributors.py   # optional
python scripts/render.py
open _site/index.html
```

## License

Apache-2.0. The data belongs to the OpenTelemetry project and its contributors.
