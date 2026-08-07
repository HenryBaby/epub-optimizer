# Changelog

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

- Added an automation dashboard with watched-folder processing, persistent job
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
