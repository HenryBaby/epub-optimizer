# Mocked Grimmory browser regression

Run from the repository with Docker available:

```sh
bash tests/ui/run.sh
# Optional: choose another writable directory shared with the Docker daemon.
UI_ARTIFACT_DIR=/home/nmo/docker-projects/epub-ui-review bash tests/ui/run.sh
```

The runner uses the matching pinned `mcr.microsoft.com/playwright:v1.56.1-noble`
browser image and `playwright@1.56.1`, installed only in the temporary container.
The repository is mounted read-only. Chromium and all Node/npm execution stay
inside this project-specific container, limited to four CPUs and 4 GiB memory.
There are no production dependencies, host browser installations or servers.
The first run needs network access to download the image and npm package.
Artifacts default to a sibling of the repository, `${repo_dir}-ui-artifacts`,
outside Git. Bind mount source directories must exist in the Docker host daemon's
filesystem as well as this development environment. Use a shared workspace path
for `UI_ARTIFACT_DIR`; a development-container-only `/tmp` path will not work with
a separate host Docker daemon.

`grimmory-workspace.cjs` loads the real template, CSS, favicon and application
JavaScript. It renders only the two Jinja placeholders (`app_version` and
`max_upload_mb`) and intercepts every browser request before transport. Grimmory
and Automation use in-memory fixtures matching their JSON status/action contracts.
Any request outside the explicit allowlist fails the run. No backend, Grimmory,
library filesystem, credentials or other homelab services are contacted.

Focused validation selector: `node tests/ui/grimmory-workspace.cjs`, with the
matching Playwright dependency supplied through `NODE_PATH` (the runner does this).
The five sequential checks cover:

- Loading, reloading and changing global tabs issue no action POSTs. The upload
  picker is hidden in the Grimmory workspace. Connect discovers folders; selecting
  folders and typing mounted paths creates only local drafts. Computed styles
  distinguish the primary Preview action from secondary Pause and quiet Refresh.
- Explicitly pause selected libraries, preview the exact draft scope, acknowledge
  maintenance, and start. Connection/folder inputs lock while Cancel safely stays
  available. Real status polling preserves selected folders, draft mounts, open
  per-file errors, expanded history and keyboard focus. Completion leaves watching
  paused. History exposes verified backups; restore requires a fresh maintenance
  acknowledgement and a snapshot-specific confirmation. Dismissing it issues no
  restore. Accepting it starts restore; cancellation and resume are explicit.
- A partial pause explains permission failure. Its persisted receipt remains
  visible after a disconnected reload. Resume stays disabled until same-instance
  reconnect, and reconnect itself never resumes. The receipt retains originally
  disabled watching. A separate 390 px dark mobile view checks labels, keyboard
  focus and horizontal overflow.
- Previewing before pausing keeps Pause watching accessible in the current
  review stage. Pausing invalidates that preview without issuing another preview
  POST; the user must explicitly preview again and acknowledge maintenance.
- After successful connection collapses its settings, a deliberately failed
  status refresh still exposes a visible alert without reopening settings or
  issuing an action POST. The injected 503 resource console message is expected;
  all other browser console errors still fail the check.

Fixtures validate the UI's request payloads and render returned watching states;
backend watch-state persistence and preservation are separately covered by
`tests/test_grimmory_watching.py`. This harness does not claim to retest the backend.

Each passing check prints a JSON line. `checks.json` records the passed checks and
failure stack when applicable. Successful runs save `desktop-disconnected.png`,
`desktop-connected-light.png`, `desktop-paused-light.png`, `desktop-active.png`, `desktop-result.png`, and
`mobile-connected-dark.png` under the chosen artifact directory. Browser console
errors and unhandled JavaScript errors fail each check. Screenshots are review
artifacts, not pixel baselines.
