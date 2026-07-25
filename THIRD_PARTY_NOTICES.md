# Third-party runtime notices

The Docker image downloads the official W3C EPUBCheck 5.3.0 release from its
[GitHub release](https://github.com/w3c/epubcheck/releases/tag/v5.3.0) at build
time and installs it under `/opt/epubcheck`. EPUBCheck is distributed under
the BSD 3-Clause License; the upstream `LICENSE.txt`, `THIRD-PARTY.txt`, and
dependency license files remain in the downloaded distribution.

The release archive is verified during the Docker build with SHA-256
`6c07e68584b2e2ce2f89fe06e1246dfead3eb36b46b340e7d93524f29dcff6c5`.

The image uses OpenJDK 17 headless from the Debian base distribution. OpenJDK
is licensed under GPLv2 with the Classpath Exception; Debian package notices
remain available under `/usr/share/doc` in the image.

EPUB Optimizer itself is licensed under AGPL-3.0-only. Its `LICENSE` and this
notice are installed under `/usr/share/doc/epub-optimizer` in the image.
