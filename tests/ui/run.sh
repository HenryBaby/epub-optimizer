#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
artifact_dir=${UI_ARTIFACT_DIR:-${repo_dir}-ui-artifacts}
mkdir -p -- "$artifact_dir"
docker run --rm --init --cpus=4 --memory=4g --shm-size=1g \
  --label com.epub-optimizer.purpose=ui-browser-validation \
  --mount "type=bind,src=$repo_dir,dst=/project,readonly" \
  --mount "type=bind,src=$artifact_dir,dst=/artifacts" \
  --env UI_ARTIFACT_DIR=/artifacts \
  --workdir /project \
  mcr.microsoft.com/playwright:v1.56.1-noble \
  bash -euc 'npm install --prefix /tmp/ui-deps --no-audit --no-fund --package-lock=false playwright@1.56.1 >/tmp/ui-install.log; NODE_PATH=/tmp/ui-deps/node_modules node tests/ui/grimmory-workspace.cjs'
