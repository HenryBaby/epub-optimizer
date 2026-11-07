# Grimmory library maintenance

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

Connect and select libraries, then use **Pause watching selected libraries** in
EPUB Optimizer before previewing. This needs no local mount or preview. Review
the persisted receipt: each library shows paused watching, already disabled
watching, or an unverified/failed update. Retry the same selection explicitly to
recover partial failures. This controls per-library watching only: queued imports,
scans, metadata writes, and external writers can still run. Wait for queued work
and pause other writers, including EPUB Optimizer watched Automation separately
if it feeds Bookdrop. Its global automation setting is outside these API writes.

Then map mounted paths, **Preview selected folders**, confirm external writers
are paused, **Back up & optimize**, review results, and explicitly **Resume previous
watching states**. Apply the same writer precautions before restore. The watching
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

## Interface and verification

Show connection status, path mappings, preview, explicit backup/run actions,
per-book results, cancellation between books, retained backups, and explicit
restore actions. Distinguish a library-files backup from a complete Grimmory
snapshot in both labels and reports.

Use temporary fixture libraries and mocked Grimmory endpoints to verify path
containment, metadata preservation, exact filenames, backup completeness,
hash/permission checks, cancellation, restart recovery, atomic publication,
failed-optimization handling, and restore conflicts. Include official EPUBCheck
on representative EPUB 2/3 inputs in the metadata-preservation test scope.

## References

- Grimmory library discovery: <https://grimmory.org/api/operations/getlibraries/>
- Grimmory API overview and stability notice: <https://grimmory.org/api/>
