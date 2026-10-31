"""Optional LangSmith tracing for future AI agents. Does nothing today.

The Ownership Check and the directory use no language model, so nothing here is
called by the daily build. When an agent that calls a model is added, wrap its entry
points with @traced("agent-name"). Tracing then turns on only if ALL of these hold:

  * LANGSMITH_TRACING=true is set in the environment,
  * LANGSMITH_API_KEY is set, and
  * the `langsmith` package is installed (it is not in requirements.txt).

Otherwise the decorator returns the function unchanged: no import, no network, no cost.
Inputs and outputs are passed through redact() first, so tokens, e-mail addresses and
other secrets are never sent. See docs/langsmith.md.
"""
import functools
import os
import re

SECRET_KEYS = re.compile(r"token|secret|password|api[_-]?key|authorization|cookie|email", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
GH_TOKEN = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
MAX_TEXT = 2000


def enabled():
    return os.environ.get("LANGSMITH_TRACING", "").lower() == "true" and bool(os.environ.get("LANGSMITH_API_KEY"))


def redact(value, _depth=0):
    """Copy of value with secret-looking keys blanked, e-mails and GitHub tokens masked, long text cut."""
    if _depth > 6:
        return "…"
    if isinstance(value, dict):
        return {k: "[redacted]" if SECRET_KEYS.search(str(k)) else redact(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth + 1) for v in value[:50]]
    if isinstance(value, str):
        text = GH_TOKEN.sub("[token]", EMAIL.sub("[email]", value))
        return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "…"
    return value


def traced(name, **meta):
    """Decorator: a LangSmith run named `name` when tracing is enabled, otherwise a no-op."""
    def wrap(fn):
        if not enabled():
            return fn
        try:
            from langsmith import traceable  # imported only when tracing is switched on
        except ImportError:
            return fn
        return functools.wraps(fn)(traceable(name=name, metadata=meta,
                                             process_inputs=redact, process_outputs=redact)(fn))
    return wrap
