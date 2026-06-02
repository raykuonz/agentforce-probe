#!/usr/bin/env bash
# Privacy & hygiene gate for agentforce-probe.
# Scans all git-tracked + staged files for things that must never be committed:
#   - real secrets (API keys, client secrets, JWTs, Salesforce org IDs)
#   - customer / engagement data (the tool is built from a real engagement;
#     none of that data may leak into the open-source repo)
#   - agent / fake-author footprints (@local identities, co-authored-by trailers)
#
# Exits non-zero (blocking the commit/push) on any hit. Run by the pre-commit
# hook and reused in CI. No network, no external deps — pure grep.

set -euo pipefail

fail=0
note() { printf '  \033[31m✗\033[0m %s\n' "$1"; fail=1; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }

# Files to scan: tracked files, minus this script and the lock file.
files=$(git ls-files | grep -vE '^scripts/check-secrets\.sh$|^uv\.lock$' || true)
[ -z "$files" ] && { echo "no tracked files to scan"; exit 0; }

echo "Privacy & hygiene scan:"

# 1. Real secrets / tokens / org IDs.
if echo "$files" | xargs grep -nIE \
  'sk-[A-Za-z0-9]{20}|client_secret[[:space:]]*=[[:space:]]*['"'"'"][A-Za-z0-9]{15}|3MVG9|\b00D[A-Za-z0-9]{12}\b|eyJ[A-Za-z0-9_-]{30}' \
  2>/dev/null; then
  note "potential secret / JWT / Salesforce org ID found above"
else
  ok "no secrets / JWTs / org IDs"
fi

# 2. Customer / engagement data (case-insensitive). These are the real-world
#    identifiers the tool was extracted from; example data must be fictional.
if echo "$files" | xargs grep -niIE \
  'pacific[ _-]?haven|tenant_concierge|leasing_assistant|ops_assistant|ops_agent_api|php-uat|php_agentforce' \
  2>/dev/null; then
  note "customer / engagement identifier found above (use fictional demo data)"
else
  ok "no customer / engagement data"
fi

# 3. Agent / fake-author footprints.
if echo "$files" | xargs grep -niIE \
  '@local\b|co-authored-by|🤖 generated|agentforce-probe@local' \
  2>/dev/null; then
  note "agent / fake-author footprint found above"
else
  ok "no agent / fake-author footprints"
fi

# 4. A real .env must never be tracked (only .env.example).
if echo "$files" | grep -qE '(^|/)\.env$'; then
  note "a real .env file is tracked — only .env.example may be committed"
else
  ok "no real .env tracked"
fi

# 5. Run artifacts (test data) must not be committed.
if echo "$files" | grep -qE 'judge-task\.json$|judge-verdicts\.json$|-JUDGING\.md$|-evidence\.md$'; then
  note "a run artifact (judge-task / verdicts / JUDGING / evidence) is tracked — these are test data, keep them gitignored"
else
  ok "no run artifacts tracked"
fi

if [ "$fail" -ne 0 ]; then
  echo ""
  echo "Privacy/hygiene gate FAILED — fix the items above before committing."
  exit 1
fi
echo "Privacy/hygiene gate passed."
