#!/usr/bin/env bash
set -euo pipefail
TEST_REPO=$(git rev-parse --show-toplevel)
export TEST_REPO
read -r run_id < /proc/sys/kernel/random/uuid
export COMPOSE_PROJECT_NAME="epubo-sync-${run_id}"
export TEST_ROOT="$TEST_REPO/tmp/grimmory-sync-integration-$run_id"
read -r TEST_DB_PASSWORD < /proc/sys/kernel/random/uuid
read -r TEST_ADMIN_PASSWORD < /proc/sys/kernel/random/uuid
read -r TEST_KOSYNC_PASSWORD < /proc/sys/kernel/random/uuid
export TEST_DB_PASSWORD TEST_ADMIN_PASSWORD TEST_KOSYNC_PASSWORD
mkdir -p "$TEST_ROOT"/{books,backups,state}
chmod 0777 "$TEST_ROOT"/{books,backups,state}
compose=(docker compose -f "$TEST_REPO/tests/integration/grimmory-sync/compose.yml")
cleanup() {
  # This UUID project was created by this invocation; never clean other resources.
  "${compose[@]}" logs --no-color > "$TEST_ROOT/services.log" 2>&1 || true
  "${compose[@]}" down --volumes --remove-orphans || true
}
trap cleanup EXIT
printf 'Isolated integration project: %s\nArtifacts: %s\n' "$COMPOSE_PROJECT_NAME" "$TEST_ROOT"
"${compose[@]}" run --rm --no-deps runner python tests/integration/grimmory-sync/runner.py prepare
"${compose[@]}" up -d db grimmory
"${compose[@]}" run --rm --no-deps runner python tests/integration/grimmory-sync/runner.py "${1:-verify}"
