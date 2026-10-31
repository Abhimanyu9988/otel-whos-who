# Internal roadmap

Now: **Ownership Check MVP** for Collector Contrib (this branch). Everything below is planned, not built.
Each phase starts only after the previous one meets its gate.

## Gate for anything below (6–8 week validation)
False-alarm rate ≤ 10% on 50 hand-checked findings · ≥ 3 corrections accepted by maintainers ·
≥ 5 findings resolved · ≥ 5 maintainers or approvers return within 30 days · average usefulness ≥ 4/5.
Targets are hypotheses, not benchmarks.

| Phase | What | Smallest first step | Depends on | Effort (est.) |
| --- | --- | --- | --- | --- |
| Historical changes | Show when owners and answers changed | Diff `data/ownership.json` and `otel-people.json` across git history; "changed this month" view | Ownership Check in daily build | 1–2 weekends |
| Missing documentation | Required documents missing or broken | Only checks backed by a written rule (e.g. CNCF's maintainers file for projects); reuse existing link checkers rather than writing one | Gate passed | 2 weekends |
| Automated fixes | Patch-ready suggestions | Mechanical fixes only (lists out of sync); downloadable patch text; never open pull requests; follow each project's AI and contribution policy | Corrections accepted ≥ 3 | 2–3 weekends |
| Verified credentials | People confirm or dispute their own entries | GitHub sign-in proves account control only; never shown as the project's recognition of a role; disputes handled via issues first | Demand from corrections | 3–4 weekends |
| Enterprise monitoring | Alerts and reports for organisations | Opt-in e-mail alerts for chosen components (free); paid monitoring only after interviews show budget | Commercial validation | Later |

## Second project
Kubernetes or Prometheus, only after the gate. Each needs its own rule set from its own written policies.

## Not planned
Ranking people, inferring employers, AI-decided answers, posting anything on anyone's behalf.
