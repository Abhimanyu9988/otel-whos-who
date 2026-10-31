# Ownership Check

Five plain-language questions about every OpenTelemetry Collector Contrib component, answered by
fixed rules from the project's own public files. No language model decides any answer.

Page: `ownership.html` · Data: `data/ownership.json` · Code: `scripts/ownership.py` · Tests: `tests/test_ownership.py`

## Answers

| Answer | Meaning |
| --- | --- |
| Yes / No | We checked, and the files clearly say so |
| Not sure | We looked, but the evidence is unclear or conflicting |
| Not checked | We did not or could not look (file missing, data stale, rule doesn't apply) |

"Not checked" is never shown as "No" and never counts against a component. Each answer also has a
status that sets its colour: `ok`, `attention` (needs a look), `info` (good to know) or `unknown`.

Every answer carries: the question, the answer, a one-line summary, the files it is based on
(linked to the exact commit and line when the build has a token), the rule it applies (the
project's own rule or ours, labelled as such) and the date it was checked. Answers that need a
look also say **what's wrong**, **why it matters** and **how to fix it**.

## The rules

Sources: each component's `metadata.yaml` ("details file"), `.github/CODEOWNERS` ("review list"),
`CONTRIBUTING.md`, and the daily snapshots in `data/activity/`.

### 1. Does this part have at least one person responsible for it?
*Project rule:* CONTRIBUTING.md says a code owner is responsible for a component (maintaining it,
triaging issues, reviewing changes).

- **Yes** — the details file lists active code owners (people or a team); or it lists none but the
  review list assigns the folder to a parent component's owners; or there is no details file but the
  review list names someone.
- **No, needs a look** — a user-facing part (receiver, exporter, processor, extension, connector,
  scraper, provider) lists nobody. Comes with a draft "looking for code owners" issue.
- **No, good to know** — the part is already marked unmaintained by the project, or it is
  shared/internal code (pkg, cmd, internal, `/internal/` sub-parts) that the default review team covers.
- **Not sure** — no details file and the review list names nobody specific.
- **Not checked** — the details file can't be parsed.

### 2. Have the people responsible approved or merged changes in this repository recently?
*Our rule.* We look for an approval or merge by any listed person, anywhere in the repository, in the
last 180 days (`data/activity/merged_prs.csv`).

- **Yes** — with a link to the most recent such pull request.
- **Not sure** — none found. The answer names nobody and says explicitly that this does not mean
  anyone is inactive: people also comment, triage, review without approving, or help elsewhere.
- **Not checked** — nobody listed, only a team listed (membership isn't public), or our review
  history doesn't cover the full 180 days.
- **This question never answers "No".** GitHub activity alone can't show that someone stopped
  looking after a part.

### 3. Do the project's lists of responsible people agree with each other?
*Our rule.* In Collector Contrib the review list is generated from the details files, so they should match.
Comparison ignores case and the approvers team the generator adds to every line.

- **No, needs a look** — someone is both active and emeritus in the details file; the review list
  has no line for a part that names people; the review list marks a part unmaintained but its details
  file doesn't; or the two name different people (listed per side). Comes with a draft issue.
- **Yes** — they match (for unmaintained parts: both name nobody).
- **Not checked** — the details file or review list is missing.

### 4. Is this part looking for more helpers?
*Project rule:* the details file's `seeking_new` flag, the `unmaintained` stability level, and the
project's open "unmaintained" issues calling for owners. **Yes** is shown as an opportunity, not a problem.

### 5. Has a change been waiting more than 30 days for the people responsible?
*Our rule.* Open, non-draft pull requests carrying both the part's label and `waiting-for-code-owners`.
`oldest_waiting` is when the oldest one was **opened** (the label date isn't recorded, so this is an upper bound).

- **Yes, needs a look** — the oldest was opened over 30 days ago.
- **No** — none waiting, or all opened within 30 days.
- **Not sure** — some are waiting but we don't know since when (data collected before this column existed).
- **Not checked** — no snapshot for the repository, or it is more than 3 days old.

## What we deliberately don't do
- Call anyone inactive, or rank people.
- Treat a missing optional file as a defect.
- Use AI to decide or word answers. Drafts are fixed templates; we never post them.

## Reporting a wrong answer
Every answer has "Report a wrong answer", which opens a prefilled issue in this repository. Each one
reported is a measured false alarm (see the success measures in the roadmap).
