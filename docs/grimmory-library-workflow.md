# Grimmory library maintenance

## Optional reader sync refresh

An optimized EPUB can retain the same rounded kilobyte size while its bytes
change. Grimmory's normal rescan can then retain a stale reader-sync fingerprint.
After optimization, open **Reader sync** to explicitly refresh the latest saved
optimization run's successful EPUBs, including an existing saved run. Failed
optimization results are excluded; unchanged-byte guards reject later external
edits. Only already indexed, uniquely matched EPUB paths are eligible, avoiding
new imports.

Use the **KOReader/KOSync** username and password used for CrossPoint sync, not
the Grimmory application login. Confirm that other library writers are paused,
then click **Refresh reader sync**. Credentials are used transiently and are not
saved in browser storage. Loading, polling, reconnecting and finishing an
optimization never start a refresh.

The operation republishes identical optimized bytes atomically at the same path
while temporarily enabling watching. Read-only KOSync GET requests verify the
fingerprint. It makes no EPUB content or metadata changes, direct database edits,
server patches or reading-progress pushes/migrations. Existing progress may map
to a different exact location when optimization changed the HTML layout; this
does not guarantee that an older XPointer still identifies the same passage.

Watching is restored to its exact state at refresh start. A durable temporary
watching receipt remains visible if cleanup fails or the process restarts.
Reconnect to that same Grimmory instance and explicitly select **Restore watching
settings**; this blocks further library writes until resolved. No recovery action
runs automatically after restart. This receipt is separate from the optimization
pause receipt: a refresh started while paused leaves watching paused, and
**Resume watching** remains a separate action after successful verification.

Contract for the manually invoked library workflow. Tests use temporary library
trees and mocked Grimmory responses; a live deployment still requires explicit
mount configuration and connection testing.

## Scope

- A separate Grimmory tab connects to the configured instance and lists its
  libraries and paths using read-only API discovery.
- Explicit pause/resume controls update only the selected libraries' watching
  through the API, preserving every other library setting. They require admin or
  manage-library permission. They never change book paths or source metadata.
- Each remote library path must map explicitly to an allowed library mount in
  the optimizer container. No Docker socket or container introspection is used.
- Users select libraries, preview the EPUB count and required backup space, and
  explicitly start a job. Application startup never starts or resumes writes.
- The normal house-style optimizer processes staged copies sequentially. A
  dedicated preservation mode protects bibliographic EPUB metadata.
- Successful files replace their originals at the same relative path and exact
  filename. Failed files retain their original bytes and receive a per-file
  diagnostic. Other formats and sidecar files are not optimized.

## Protected metadata

The normal optimizer can add its version marker and repair package metadata.
Library maintenance must instead enable strict preservation: retain the OPF
metadata subtree, namespace declarations, package unique-identifier and prefix
bindings; skip metadata and NCX identifier repairs; and compare protected
metadata against the original before publishing. Existing metadata errors may
remain reported as legacy issues.

The manifest necessarily changes when CSS or font resources change. EPUB file
bytes, size, and hashes therefore change. Preserving bibliographic metadata and
paths does not prevent a library manager from noticing a changed file.

## Backup and restore contract

A verified backup of every selected library directory must complete before any
EPUB is replaced. Include non-EPUB files, sidecars, covers, empty directories,
relative paths, supported permissions, and timestamps. Store the backup outside
the source libraries and optimizer watcher/output folders. Do not use hard links
to mutable originals. Detect symlinks, special files, overlapping roots, and
unsupported metadata before proceeding, rather than following them implicitly.

Record file hashes and filesystem metadata in a persisted manifest. Compare the
source tree again after copying and reject changes observed during the copy.
Before replacing each EPUB, recheck its identity and hash. A tree-copy backup is
not an atomic filesystem snapshot: a consistent backup requires a maintenance
window with external writers and watchers paused.

Stage each result outside the library. Publication must use an atomic rename
on the destination filesystem and preserve the original file's supported
permissions, ownership, and timestamps. Use a temporary name without an EPUB
extension and remove it after any failure. Never write partial EPUB bytes to the
live filename. Persist each successful replacement and its before/after hashes.

Restore must verify all backup hashes before making any changes, then restore
the original bytes and supported filesystem metadata at their original paths.
Unexpected additions, missing files, or external edits require conflict handling;
they must never be silently overwritten or deleted. Keep the backup after a
restore. Interrupted jobs must be visible and recoverable, with no automatic
continuation after application restart.

## Grimmory state and maintenance window

Library files and Grimmory database records are distinct. A directory backup
cannot restore reading progress, shelves, catalog relationships, or database
updates caused by Grimmory noticing replacements. EPUB metadata preservation
alone cannot guarantee database preservation.

The implemented backup scope is library directories only, with Grimmory's
watchers/writers paused and database state managed separately. The UI identifies
this scope explicitly. Coordinated library and database backup/restore would
require a separate supported database backup mechanism and maintenance procedure;
it is not provided or implied by a library-folder restore.

The optimizer must not attempt to pause, restart, inspect, or reconfigure host
containers. No live integration or library mutation is part of development tests.

Connect and select libraries, then use **Pause watching** in
EPUB Optimizer before previewing. This needs no local mount or preview. Review
the persisted receipt: each library shows paused watching, already disabled
watching, or an unverified/failed update. Retry the same selection explicitly to
recover partial failures. This controls per-library watching only: queued imports,
scans, metadata writes, and external writers can still run. Wait for queued work
and pause other writers, including EPUB Optimizer watched Automation separately
if it feeds Bookdrop. Its global automation setting is outside these API writes.

Then map mounted paths, **Preview folders**, confirm external writers
are paused, **Back up & optimize**, review results, and explicitly **Resume watching**. Apply the same writer precautions before restore. The watching
receipt survives restarts, and watching remains paused after completion until
explicit resume. Reconnect to the same instance to recover it after restart.
Resume restores originally enabled watching only; originally disabled libraries
remain disabled. Partial failures stay visible for explicit recovery.

`POST /grimmory/pause-watching` accepts `{"library_ids": [7, 8]}`;
`POST /grimmory/resume-watching` accepts `{"session_id": "saved-session-id"}`.
Both return status including `watcher_maintenance`, or null before a session.
Status reads, connection, page loading, polling, job start/completion, and shutdown
never issue watching writes. Watching changes are disabled during active jobs.
Pausing invalidates any prior preview; refresh and preview again before starting.
Folder selections and unsaved local mappings survive a watching-status rerender.
These controls do not provide complete Grimmory maintenance or database backup.

## Local backup management

The **Backups** view lists local snapshots, including while disconnected. Select
one to review its timestamp, identity, counts, size, and mapped folder scope.
**Restore snapshot** requires a same-instance connection, a fresh writer
acknowledgement and a scope-specific confirmation. Selecting another snapshot or
changing views clears that acknowledgement.

**Delete backup** requires a separate irreversible confirmation with the selected
snapshot ID and date. `POST /grimmory/delete-snapshot` accepts
`{"snapshot_id": "saved-snapshot-id", "confirmed": true}` and returns full status.
It deletes the selected local backup without touching current library files or
requiring a Grimmory connection. No deletion starts from page loading, status
polling, view changes, or selection. Active jobs and pending temporary watching
recovery block deletion. A failed or interrupted deletion retains a `deleting`
entry for explicit **Retry deletion**, with restore disabled; errors must never
be presented as successful deletion. Removing a backup also removes its future
restore capability and may make associated reader-sync refresh unavailable.

## Interface and verification

Use the shared application width with compact **Optimize**, **Backups**, and
**History** navigation. Keep watching status and controls together. Optimize shows
only the current workflow stage and one contextual writer acknowledgement; Reader
sync retains its separate fresh acknowledgement. Collapse connected settings,
show per-book results and cancellation between books, and keep backups separate
from run history. Distinguish a library-files backup from a complete Grimmory
snapshot in both labels and reports.

If a job fails before processing any books, inspect its message in the Grimmory
tab's current job and history. Backup filesystem failures identify the operation
(directory creation, copying, ownership/metadata preservation, verification,
manifest persistence, or sync) and errno class without exposing raw exception
text, credentials, or remote URLs. The same message is saved with the job and
available in status responses; a server traceback is not required.

Permission failures during backup directory creation require checking the
service identity's write and parent-directory traversal access to the backup
mount. Ownership-preservation failures instead require checking source
owner/group compatibility with the service identity and backup filesystem.
Other messages distinguish space/quota exhaustion, read-only mounts, and rejected
filesystem operations. Correct the reported condition, then preview and start
again. These diagnostics do not establish the cause of an earlier generic
failure or relax metadata, backup verification, or durability requirements.
An incomplete backup is never offered as a ready snapshot; no books are optimized
until the verified backup completes. Unexpected errors retain a generic message.

Use temporary fixture libraries and mocked Grimmory endpoints to verify path
containment, metadata preservation, exact filenames, backup completeness,
hash/permission checks, cancellation, restart recovery, atomic publication,
failed-optimization handling, and restore conflicts. Include official EPUBCheck
on representative EPUB 2/3 inputs in the metadata-preservation test scope.

## References

- Grimmory library discovery: <https://grimmory.org/api/operations/getlibraries/>
- Grimmory API overview and stability notice: <https://grimmory.org/api/>
