# Grimmory native KOSync integration

From the repository root, with the project's development image available:

```sh
bash tests/integration/grimmory-sync/run.sh
```

This is an opt-in, isolated integration test, outside the normal pytest suite.
It runs the unmodified official `ghcr.io/grimmory-tools/grimmory:v3.5.0` image
and MariaDB on a fresh private Compose network, without published ports. Both
server images are pinned by digest for reproducibility.
The runner uses `epub-optimizer-dev:local` (`TEST_RUNNER_IMAGE` overrides it),
the current source mounted read-only, Java, and the image's official EPUBCheck.
All Python code and application work execute inside these containers.
Resource limits total 6 CPUs and 9 GiB (Grimmory 3 CPUs/5 GiB,
MariaDB 1 CPU/1 GiB, runner 2 CPUs/3 GiB); JVM heap is capped at 3 GiB.
Run this separately from other intensive validation workloads.

The launcher creates UUID-named project resources and generated credentials,
bootstraps its first administrator through the official API, imports a generated
EPUB 3 fixture, and seeds progress through the native KOSync API. It does not
connect to an existing library or server and does not patch Grimmory or its DB.
No real books or credentials are required. The fixture includes a 922-character
quoted epigraph, stable text IDs, and embedded publication metadata.

Assertions cover changed native hash after real optimization, missing new-hash
lookup before refresh, identical optimized bytes after refresh with a new inode,
the same indexed book ID and book count, the same native progress and percentage,
temporary watching restored to false, the original pause receipt retained,
an existing unindexed EPUB remaining unindexed, sidecar/content/metadata/ID
preservation, no extra EPUBs or partial files, credentials absent from saved JSON,
and an already-current repeat preserving watching=true without republishing.

Artifacts remain under the printed ignored `tmp/grimmory-sync-integration-*`
directory: indexed Book DTO, optimizer state, backup snapshot, result JSON, and
service logs. On exit the launcher removes only this invocation's UUID Compose
project containers, network, and volumes. Images and local artifacts remain.
The test never mounts the Docker socket into an application container.

For bootstrap/API contract diagnosis without optimization:

```sh
bash tests/integration/grimmory-sync/run.sh bootstrap
```

Behavioral validation selector: the full `run.sh` command above. Success requires
exit status zero and `state/result.json` containing `"status": "passed"`.
