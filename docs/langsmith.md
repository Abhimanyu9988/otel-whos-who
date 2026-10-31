# LangSmith integration — architecture (dormant)

**Status: nothing is traced and nothing is billed.** No part of the build calls a language model.
`scripts/tracing.py` provides `@traced(name)`, which returns functions unchanged unless
`LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY` is set and the `langsmith` package is installed.
`langsmith` is deliberately not in `requirements.txt`.

## When it switches on
Only when an agent actually calls a model. Planned first users, in order:
1. **Research & Data agent** — reviews a weekly sample of Ownership Check findings against the
   source files and proposes rule fixes. Deterministic checks stay deterministic; the agent only reviews.
2. **Chief of Staff agent** — writes the weekly founder report from analytics and findings data.

## What gets traced
- Each agent run: inputs (redacted), tool calls, model, tokens, cost, latency, outcome.
- Tags: `agent`, `rules_version`, `run_type` (scheduled / manual).
- Never traced: tokens, keys, e-mail addresses, visitor data. `redact()` blanks secret-looking keys
  and masks e-mails and GitHub tokens before anything is sent; text is cut at 2,000 characters.

## Evaluation
Dataset: the hand-checked Ownership Check findings (target 50) plus documented role questions
("who owns receiver/kafka?") with answers taken from the source files.
Metrics: citation validity (every claimed file/line exists), role classification accuracy,
agreement with the deterministic answer, cost per useful answer, latency.

## Budgets (proposed, need approval)
- Hard cap per agent run (tokens) and per month (USD) enforced in code before any model call.
- Tracing stays on the free tier; sampling if volume grows.
- Any spend requires the founder's approval first.
