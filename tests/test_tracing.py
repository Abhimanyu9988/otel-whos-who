"""tracing.py stays a no-op unless explicitly enabled, and redacts secrets."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import tracing  # noqa: E402


class Tracing(unittest.TestCase):
    def test_off_by_default_returns_the_same_function(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            def f(x):
                return x + 1
            self.assertIs(tracing.traced("agent")(f), f)
            self.assertFalse(tracing.enabled())

    def test_needs_both_flag_and_key(self):
        with mock.patch.dict(os.environ, {"LANGSMITH_TRACING": "true"}, clear=True):
            self.assertFalse(tracing.enabled())
        with mock.patch.dict(os.environ, {"LANGSMITH_API_KEY": "k"}, clear=True):
            self.assertFalse(tracing.enabled())

    def test_enabled_without_the_package_is_still_a_no_op(self):
        with mock.patch.dict(os.environ, {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "k"}, clear=True), \
             mock.patch.dict(sys.modules, {"langsmith": None}):
            def f():
                return 1
            self.assertIs(tracing.traced("agent")(f), f)

    def test_redact(self):
        out = tracing.redact({"github_token": "abc", "note": "mail me at a.b@example.com",
                              "nested": [{"Authorization": "Bearer x", "text": "ghp_" + "a" * 36}]})
        self.assertEqual(out["github_token"], "[redacted]")
        self.assertEqual(out["note"], "mail me at [email]")
        self.assertEqual(out["nested"][0]["Authorization"], "[redacted]")
        self.assertEqual(out["nested"][0]["text"], "[token]")


if __name__ == "__main__":
    unittest.main()
