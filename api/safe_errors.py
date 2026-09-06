"""Make an exception safe to store and to show.

An error message is user-visible output (CLAUDE.md sec. 2). That rule was
written after 2026-09-05, when a misconfigured `API_BASE_URL` put the live
database password onto a public page through an error string. The fix then
was in `frontend/api_client.py`, and it covered exactly one path: the
frontend's own HTTP failures.

Step 11 opens a second path. `monitor_runs.error` and
`synthesis_runs.error` store the text of whatever a scheduled job caught,
`GET /ops/status` reads those rows back, and the Ops page prints them. So
an exception raised inside an unattended cron — which is precisely where
`DATABASE_URL` and `ANTHROPIC_API_KEY` live in the environment — now has a
route to a browser. psycopg2's `OperationalError` can carry the DSN it
failed to connect with; an HTTP client can put a header or a URL into its
message. Nothing about that is hypothetical: this project has already paid
once for assuming exception text is internal.

`scrub()` is deliberately dumb and belt-and-braces:

  1. Redact the *actual values* of the secrets this process holds, read
     from the environment at call time. Exact string replacement, so it
     cannot be defeated by an unexpected message format.
  2. Redact anything *shaped* like a secret even if it is not one of ours
     — a `user:password@host` userinfo block, an `sk-ant-...` key — which
     is what catches the secret this process did not know it had.
  3. Truncate. An error column is not a log, and a 40 KB traceback in a
     page's error box helps nobody.

It never tries to be clever about which part of a message is safe. Anything
that looks like a credential goes, even at the cost of redacting something
innocent: a slightly less readable error is a cheaper mistake than a leaked
one.
"""
import os
import re

# The secrets this process is known to hold. Values, not names — the name is
# safe to print (and naming the variable is how the 2026-09-05 fix made a
# confusing failure actionable); the value never is.
SECRET_ENV_VARS = (
    "DATABASE_URL",
    "DATABASE_URL_READONLY",
    "ANTHROPIC_API_KEY",
)

# Credentials in a URL: scheme://user:password@host. The password is the
# part that matters, but the username is an account name, so both go.
_USERINFO = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")

# Anthropic keys have a fixed, recognisable prefix. Matched on shape so a
# key pasted into a message by some library we do not control is caught even
# when it is not the key in our own environment.
_API_KEY = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")

MAX_LENGTH = 2000

REDACTED = "[redacted]"


def scrub(text) -> str:
    """The message with every credential this can recognise removed."""
    cleaned = str(text)

    for name in SECRET_ENV_VARS:
        value = os.environ.get(name)
        # `if value` guards the empty string: replacing "" would splice the
        # placeholder between every character in the message.
        if value:
            cleaned = cleaned.replace(value, f"[{name} redacted]")

    cleaned = _USERINFO.sub(lambda m: f"{m.group('scheme')}{REDACTED}@", cleaned)
    cleaned = _API_KEY.sub(REDACTED, cleaned)

    if len(cleaned) > MAX_LENGTH:
        cleaned = cleaned[:MAX_LENGTH] + "... [truncated]"
    return cleaned


def describe(exc: BaseException) -> str:
    """A caught exception as one scrubbed line, type included.

    The type is worth keeping: `OperationalError` and `ValueError` need
    different responses, and a bare message often does not say which it was
    (psycopg2's "server closed the connection unexpectedly" reads like a
    network blip in either case).
    """
    return scrub(f"{type(exc).__name__}: {exc}")
