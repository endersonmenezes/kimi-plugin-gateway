# Changelog

All notable changes to Kimi Plugin Gateway are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project will use [Semantic Versioning](https://semver.org/spec/v2.0.0.html) for Gateway releases. Individual plugin release tags continue to follow `<id>-v<upstream-version>-gateway.<revision>`.

## [Unreleased]

### Added

- Issue Forms and GitHub Actions workflows for converting Claude plugins and updating registered upstream revisions.
- Pull request-based review with CODEOWNERS and validation before publication.
- Real Git submodules pinned to full upstream commits, including annotated-tag resolution.
- Declarative overlays for maintaining Kimi-specific changes without editing upstream files.
- Deterministic conversion of Claude manifests and explicit reporting of capabilities that require human review.
- Path, symlink, archive, provenance, and stale-overlay safety checks.
- Standalone per-plugin ZIP archives with SHA-256 checksums and immutable release tags.
- A custom Kimi marketplace with independent installation for each plugin.
- Initial Impeccable 4.10.0 adaptation, pinned to upstream commit `b49177d32788f2dc585c42831d845dacf1ebed2c`.
- English documentation for installation, development, contributions, security, and third-party licensing.

### Fixed

- Made Git test fixtures independent of machine-specific author configuration so annotated-tag tests also pass on clean CI runners.
- Provided the workflow token to GitHub CLI commands used by IssueOps and plugin releases, fixing release publication on GitHub Actions.
- Made manually dispatched IssueOps workflows verify the issue label before running conversion or update operations.
- Translated source-resolution, duplicate-ID, and required-field errors exposed by IssueOps to English.
- Made conversion retries remove the empty plugin directory left after deleting a submodule from an existing IssueOps branch.

[Unreleased]: https://github.com/endersonmenezes/kimi-plugin-gateway/compare/main...HEAD
