"""components.count(): the per-label snapshot, including the new oldest_waiting column."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import components  # noqa: E402

REPO = "open-telemetry/opentelemetry-collector-contrib"


def pr(number, created, *labels, draft=False):
    return {"number": number, "title": "", "createdAt": created + "T10:00:00Z", "isDraft": draft, "labels": set(labels)}


class Count(unittest.TestCase):
    def test_oldest_waiting_is_the_oldest_open_non_draft_pr_waiting_for_owners(self):
        prs = [pr(1, "2026-09-01", "receiver/x", "waiting-for-code-owners"),
               pr(2, "2026-07-15", "receiver/x", "waiting-for-code-owners", draft=True),   # drafts don't count
               pr(3, "2026-06-01", "receiver/x"),                                          # not waiting
               pr(4, "2026-10-01", "receiver/x", "waiting-for-code-owners")]
        rows = {r["label"]: r for r in components.count(REPO, {"receiver/x"}, [], prs, "2026-10-31")}
        self.assertEqual(rows["receiver/x"]["waiting_owners"], 2)
        self.assertEqual(rows["receiver/x"]["oldest_waiting"], "2026-09-01")
        self.assertEqual(rows["receiver/x"]["open_prs"], 3)

    def test_no_waiting_leaves_the_column_empty(self):
        rows = components.count(REPO, {"receiver/x"}, [], [pr(1, "2026-09-01", "receiver/x")], "2026-10-31")
        self.assertEqual(rows[0]["oldest_waiting"], "")

    def test_new_column_is_last_so_existing_readers_are_unaffected(self):
        self.assertEqual(components.FIELDS[-1], "oldest_waiting")
        self.assertEqual(components.FIELDS[:-1], ["date", "repo", "label", "open_issues", "bugs", "needs_triage",
                                                  "newcomer", "oldest_issue", "open_prs", "waiting_owners", "owner_call"])


if __name__ == "__main__":
    unittest.main()
