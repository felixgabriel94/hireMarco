#!/usr/bin/env bash
# Pre-commit check: tests pass and no secret-shaped string is staged or tracked.
set -u
cd "$(dirname "$0")/.."
status=0
uv run pytest || status=1
# secret shapes: bearer tokens, Meta/Graph tokens (EAA...), OpenAI-style keys, Twilio SIDs, ElevenLabs keys, private keys
pattern='(Bearer [A-Za-z0-9._-]{20,}|EAA[A-Za-z0-9]{40,}|sk-[A-Za-z0-9]{20,}|AC[0-9a-f]{32}|xi-api-key[: =]+[A-Za-z0-9]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY)'
if git ls-files -z | xargs -0 grep -nE "$pattern" -- 2>/dev/null | grep -v 'scripts/check.sh'; then
  echo "secret-shaped string in tracked files" >&2; status=1
fi
if git diff --cached | grep -E "^\+.*$pattern" | grep -v 'scripts/check.sh'; then
  echo "secret-shaped string staged" >&2; status=1
fi
if [ $status -eq 0 ]; then echo "check: ok"; else echo "check: FAILED"; fi
exit $status
