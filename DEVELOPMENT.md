# Development Guide

This guide describes the local development workflow for Kimi Plugin Gateway.

## Prerequisites

- Python 3.12 or newer; only the Python standard library is required.
- Git with submodule support.
- GitHub CLI (`gh`) for optional Issue, PR, and release operations.
- Kimi Code CLI for runtime plugin verification.

## Set up the repository

```bash
git clone --recurse-submodules https://github.com/endersonmenezes/kimi-plugin-gateway.git
cd kimi-plugin-gateway
git submodule update --init --recursive
```

No dependency installation step is required.

## Run the checks

Run the complete test suite:

```bash
PYTHONPATH=scripts python3 -m unittest discover -s tests -v
```

Validate and package one plugin:

```bash
PYTHONPATH=scripts python3 -m gateway validate --plugin-id impeccable --repo-root .
PYTHONPATH=scripts python3 -m gateway package --plugin-id impeccable --output-dir dist --repo-root .
```

Remove `dist/` and Python cache directories before committing. The repository must not contain generated archives, temporary files, credentials, or local Kimi configuration.

## Project structure

```text
plugins/<id>/
  gateway.json          # Upstream URL, requested ref, full commit, and release revision
  kimi.plugin.json      # Kimi plugin manifest
  overlays/             # Optional Gateway-maintained replacements and additions
  upstream/             # Real Git submodule pinned to a full commit
scripts/gateway/        # Standard-library Python automation
.github/                # Issue Forms, workflows, and ownership rules
marketplace.json        # Independent plugin installation sources
```

The main module boundaries are:

- `issues.py`: Issue Form parsing and input validation.
- `config.py`: plugin configuration, versions, tags, and release URLs.
- `conversion.py`: deterministic Claude-to-Kimi manifest conversion.
- `operations.py`: conversion, update, and real submodule operations.
- `overlays.py`: staging-only overlay application.
- `validate.py`: structural and path-safety validation.
- `package.py`: standalone ZIP and checksum generation.
- `release.py`: per-plugin selection from a push event.
- `cli.py`: command-line interface shared by local development and Actions.

## Convert or update locally

Conversion reads public upstream content but never runs its installers, hooks, or package managers:

```bash
PYTHONPATH=scripts python3 -m gateway convert \
  --repository-url https://github.com/<owner>/<repo> \
  --ref v1.2.0 \
  --plugin-id example \
  --repo-root .
```

Update an existing plugin:

```bash
PYTHONPATH=scripts python3 -m gateway update \
  --plugin-id example \
  --ref v1.3.0 \
  --repo-root .
```

Both commands also accept `--issue-event <event.json>` for the IssueOps workflows.

## Overlays

Never edit files inside `upstream/` to maintain a Gateway adaptation. Instead, mirror the upstream path under `overlays/`.

For example, an overlay at:

```text
plugins/example/overlays/.claude/skills/example/SKILL.md
```

replaces this file only in the packaged staging tree:

```text
plugins/example/upstream/.claude/skills/example/SKILL.md
```

New files use the same rule. Declared removals belong in `overlays.remove` in `gateway.json`. Updates stop when an existing overlay or removal target disappears upstream; resolve that case in a reviewed manual PR.

## Tests and review

- Add or update tests for behavior changes and follow the existing `unittest` style.
- Use temporary local Git repositories for submodule and update tests.
- Keep upstream execution prohibited in implementation and tests.
- Run focused tests while iterating and the complete suite before committing.
- Keep public-facing documentation and contribution guidance in English.
- Do not claim Kimi runtime compatibility based only on structural tests; verify installation and Skill loading with the real CLI when changing those paths.

All changes require a pull request and CODEOWNER review. See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow.

## Release revisions

Plugin tags use `<id>-v<sourceVersion>-gateway.<revision>`.

- `sourceVersion` comes from the upstream manifest, never from the ref name.
- Reset `releaseRevision` to `1` when the upstream version changes.
- Increment it when only the Gateway adaptation changes.
- Update the corresponding `marketplace.json` source URL in the same PR.
- Never replace an existing release or asset.
