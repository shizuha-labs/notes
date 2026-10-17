#!/usr/bin/env bash
# NTS-58/NTS-67 — fail-closed migration-convergence gate.
#
# Shared by:
#   * .forgejo/workflows/deploy.yml  (post-rollout, via kubectl exec)
#   * notes/tests/test_nts67_migration_gate.py  (isolated red/green path proof)
#
# Why a shared script (NTS-67): the deploy gate's FAILURE path was never
# exercised, and its diagnostic (`showmigrations notes`) was narrower than the
# check (`migrate --check` checks every app). Keeping the gate logic in one
# file means the test executes the exact shell the deploy runs — not an
# approximation — and the red-path diagnostic is project-wide so it names the
# real (possibly non-notes) app with unapplied migrations.
#
# exit 0 when every app's migrations are applied; exit 1 (after printing the
# project-wide diagnostic) when any migration is unapplied.
set -euo pipefail

# The interpreter that owns manage.py, and the Django management module.
# Defaults match the production image; tests override PYTHON_BIN/SETTINGS_MODULE.
PYTHON_BIN="${PYTHON_BIN:-/app/.venv/bin/python}"
SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-}"

run_dj() {
  local args=("$@")
  if [ -n "$SETTINGS_MODULE" ]; then
    DJANGO_SETTINGS_MODULE="$SETTINGS_MODULE" "$PYTHON_BIN" manage.py "${args[@]}"
  else
    "$PYTHON_BIN" manage.py "${args[@]}"
  fi
}

if run_dj migrate --check --noinput; then
  echo "OK schema converged — no unapplied migrations"
  exit 0
fi

echo "::error::unapplied migrations after deploy — schema did not converge"
echo "--- showmigrations (all apps) ---"
run_dj showmigrations || true
echo "--- migrate --plan (all apps, unapplied => [X] applied / [ ] pending) ---"
run_dj migrate --plan || true
echo "--- migrate.log tail (stderr is NOT redirected there; see NTS-58 §6a) ---"
tail -40 /var/log/django/migrate.log 2>/dev/null || true
exit 1
