# Visitor analytics — design (not switched on)

**Status: off.** `site/analytics.js` is loaded by the Ownership Check page, but no build defines
`window.WW_ANALYTICS`, so nothing leaves the browser. Events are only kept in memory
(`window.WW.events`) for local debugging. Turning it on needs the founder's approval, a provider
account, and a privacy notice update.

## Principles
- No cookies, no localStorage, no fingerprinting. The session id lives in memory for one page load,
  so "returning visitors" can't be counted until a consented, documented mechanism is added.
- Respect Do Not Track and Global Privacy Control: if either is set, nothing is sent.
- Allow-list only: unknown events and properties are dropped in `analytics.js`.
- Never send text visitors type (search terms, pasted links) — only whether it matched.
- Component labels are public project names and may be sent; GitHub handles are never sent.
- Aggregate geography only (country), from the provider's IP lookup, with IPs not stored.

## Events (snake_case, `area_action`)

| Event | Properties | Answers |
| --- | --- | --- |
| `page_viewed` | `page` | Visitors, most viewed pages |
| `ownership_lookup` | `input_kind` (url / name), `result` (found / not_found / other_repo) | Lookup success; demand for other repos |
| `ownership_report_viewed` | `component`, `attention`, `unknown` | Components analysed by visitors; which parts people care about |
| `ownership_filter_changed` | `filter` | Which lists people use |
| `ownership_sources_opened` | `component`, `question` | Whether people check the evidence |
| `ownership_draft_copied` | `component`, `question` | Fix intent |
| `ownership_feedback` | `component`, `question`, `verdict` (right / wrong) | Usefulness and false-alarm rate |
| `ownership_report_link_clicked` | `component`, `question` | Reserved; wrong-answer reports are counted from GitHub issues |

## First funnel
`page_viewed` → `ownership_lookup (found)` → `ownership_report_viewed` → `ownership_sources_opened` →
`ownership_draft_copied` or `ownership_feedback`.

## Weekly founder report (once enabled)
Visitors and lookups; lookup success rate; top 10 components viewed; findings with attention viewed;
drafts copied; feedback right vs wrong (plus wrong-answer issues on GitHub); requests for other repos.

## Provider
PostHog is the default candidate (free tier covers this scale). `analytics.js` posts a small JSON
body to a configured endpoint; the exact provider payload is wired up when it is switched on.
