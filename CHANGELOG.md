# Changelog

> Release dates below are the dates of the tagged commits. These historical
> entries were backfilled; they do not establish exact publication times.

## Unreleased — 1.3.0 (dev testing)

This version is under development and is not a stable release.

### Added

- Add manual Grimmory library discovery for mapped folders and full-folder
  backups, with restore support and no automatic runs.
- Add strict metadata preservation for library jobs while retaining exact
  filenames and folder layouts. Folder backups exclude Grimmory's database and
  application state.

### Fixed

- Recognize multi-paragraph opening epigraphs, correct stale paragraph roles,
  and preserve the following narrative flow.

## 1.2.8 - 2026-10-29

### Fixed

- Preserve anchor-only empty elements during cleanup and retain their wrapper
  chains so referenced OPF fragments are not lost.
- Preserve legacy centered block markup and remove known Amazon conversion
  attributes.

## 1.2.7 - 2026-10-25

### Fixed

- Preserve EPUB 3 navigation and structural containers during normalization.
- Prevent paragraphs and headings from wrapping block content, avoiding
  invalid XHTML and introduced EPUBCheck RSC-005 errors.

## 1.2.6 - 2026-08-30

### Fixed

- Normalize NCX `playOrder` values across `navPoint`, `navTarget`, and
  `pageTarget` elements to prevent introduced EPUBCheck RSC-005 errors.

## 1.2.5 - 2026-08-27

### Fixed

- Wrap inline content directly inside blockquotes so normalization cannot
  introduce invalid XHTML or EPUBCheck RSC-005 errors.

## 1.2.4 - 2026-08-27

### Added

- Add a dedicated development container and document its dependency setup.

### Fixed

- Prevent normalization from creating invalid direct-body inline elements such
  as `<em>` in XHTML content documents.

## 1.2.3 - 2026-08-07

### Fixed

- Make failed-job reprocessing a clear single-click action with immediate
  queuing feedback.
- Mark the matching failure history entry as requeued and remove its stale
  action button while retaining the prior attempt for audit history.
- Show Reprocess only when the retained failed EPUB is still available.

## 1.2.2 - 2026-08-07

### Fixed

- Remove obsolete `META-INF/encryption.xml` records when their obfuscated font
  resources are removed during style and font normalization.
- Preserve encryption records for resources that remain in the EPUB, and remove
  `encryption.xml` only when no encrypted resources remain.

## 1.2.1 - 2026-07-26

### Fixed

- Publish validated automation output safely when `/tmp` and the mounted
  `/output` directory are on different filesystems.
- Keep destination publication atomic by copying to a non-EPUB `.part` file in
  an isolated per-job staging directory on the output filesystem before
  replacing the final filename.
- Preserve failed source EPUBs for retry through the existing Reprocess action.

## 1.2.0 - 2026-07-26

### Highlights

- Expanded the automation dashboard with watched-folder processing, persistent job
  history, failed-job reprocessing, retention controls, and batch report export.
- Added analyze, dry-run preview, validation-only, direct optimization, and
  service-health APIs.
- Added deterministic EPUB packaging, embedded optimization reports, image
  diagnostics, publisher-CSS preservation, and broader semantic normalization.
- Added link, anchor, duplicate-ID, navigation, and package-integrity checks and
  repairs.
- Bundled official EPUBCheck 5.3.0 in the Docker image and now validate every
  source EPUB and the exact optimized archive that is published.
- Added conservative automatic repairs for supported OPF metadata, manifest,
  navigation, and local-reference errors.
- Added explicit `clean`, `legacy_issues`, and `unavailable` validation outcomes
  to the UI, API, automation history, and exported reports.
- Block optimized output when it introduces a new EPUBCheck diagnostic or a
  diagnostic at a new identifiable resource.
- Revalidate previously optimized EPUBs whenever they are processed again.

### Validation semantics

- `clean` means the optimized EPUB has no EPUBCheck errors.
- `legacy_issues` means errors remain, but they are represented in the source
  baseline and the optimizer did not introduce a new diagnostic or identifiable
  resource. It does not mean the EPUB passes EPUBCheck with zero errors.
- Repeated occurrence counts for an existing diagnostic can change when
  equivalent XHTML is serialized. Such count-only changes are advisory when the
  input baseline already represents the same diagnostic and resource.
- `unavailable` means EPUBCheck could not run; built-in archive and structural
  validation still runs and the outcome is reported explicitly.

### Runtime and licensing

- The Docker image installs EPUBCheck 5.3.0 from the official W3C release,
  verifies its SHA-256 checksum, and includes a headless OpenJDK runtime.
- EPUBCheck and runtime license provenance is documented in
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- EPUB Optimizer remains licensed under AGPL-3.0-only.

## 1.1.6 - 2026-07-14

### Fixed

- Preserve heading roles when they are reliable, and reclassify them when needed.
- Preserve centered and right-aligned heading roles outside chapter contexts
  while identifying chapter-level `h1` headings correctly.

## 1.1.5 - 2026-07-14

### Improved

- Improve role classification on repeated optimization, including persisted
  part, front-matter, section, and chapter roles.
- Classify short metadata pages more accurately.

## 1.1.4 - 2026-07-13

### Fixed

- Keep failure reports outside the data volume and save them under `/failed`.
- Preserve repeat optimizer roles across processing.

## 1.1.3 - 2026-07-13

### Improved

- Archive processed source EPUBs.

## 1.1.2 - 2026-07-13

### Added

- Add structured failure diagnostics with stage, type, detail, and path fields
  across manual jobs, automation history, and JSON failure reports.
- Show expandable failure details in the interface.

## 1.1.1 - 2026-07-13

### Improved

- Refresh the README showcase and make minor interface wording and versioned
  asset updates.

## 1.1.0 - 2026-07-13

### Added

- Add an API and interface action to clear automation history.
- Document the optional failed-folder mount.

## 1.0.7 - 2026-07-13

### Added

- Add a watched-folder automation manager with polling and file-stability
  checks, configurable suffixes, output handling, and failure history.
- Add watch and output mounts and a separate Automation tab.

## 1.0.6 - 2026-07-13

### Improved

- Use relative static asset URLs and an explicit Compose volume name.
- Update the README showcase.

## 1.0.5 - 2026-07-12

### Improved

- Add versioned static asset URLs for cache busting.

## 1.0.4 - 2026-07-12

### Improved

- Improve output handling, EPUB structure normalization, and drop-zone controls.

## 1.0.3 - 2026-07-12

### Improved

- Refine folder selection usability.

## 1.0.2 - 2026-07-12

### Added

- Add folder batch selection and set the Compose container name.

## 1.0.1 - 2026-07-12

### Added

- Add a favicon.

## 1.0.0 - 2026-07-12

### Added

- Record the initial release of the existing Docker web application, supporting
  EPUB 2 and EPUB 3, house-style normalization, font cleanup, and image-byte
  preservation.
- Add release archive and download cleanup and image provenance labels.
