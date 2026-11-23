# Contributing to Kimi Plugin Gateway

Thank you for contributing. This project converts and distributes Claude plugins as independently installable Kimi plugins while preserving upstream provenance and requiring human review.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- Request a plugin conversion or upstream update through [GitHub Issues](https://github.com/endersonmenezes/kimi-plugin-gateway/issues/new/choose).
- Report defects in conversion, validation, packaging, workflows, or documentation.
- Improve tests, contributor documentation, and existing adaptations.
- Propose overlays for demonstrated Kimi incompatibilities.

For security-sensitive reports, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Before you start

- Search existing Issues and pull requests for related work.
- Read [DEVELOPMENT.md](DEVELOPMENT.md) for setup, architecture, and test commands.
- Open an Issue before substantial changes so the approach can be discussed.
- Keep changes scoped. Do not reformat unrelated files or mix multiple plugins into one review unless the change requires it.

Public-facing documentation, code identifiers, commit messages, pull requests, and review discussions should use English.

## Development workflow

1. Fork the repository if you do not have write access.
2. Create a descriptive branch from `main`.
3. Initialize submodules with `git submodule update --init --recursive`.
4. Make focused changes with tests and documentation.
5. Run the complete suite:

   ```bash
   PYTHONPATH=scripts python3 -m unittest discover -s tests -v
   ```

6. Validate and package every affected plugin:

   ```bash
   PYTHONPATH=scripts python3 -m gateway validate --plugin-id <id> --repo-root .
   PYTHONPATH=scripts python3 -m gateway package --plugin-id <id> --output-dir dist --repo-root .
   ```

7. Remove generated archives and caches, then commit using a clear Conventional Commit-style message such as `fix: reject unsafe archive paths`.
8. Push your branch and open a pull request with the provided template.

## Rules for plugin adaptations

- Use a real Git submodule pinned to a full upstream commit.
- Do not create a fork merely to maintain a Kimi adaptation.
- Never edit upstream files inside `upstream/`; use reviewed overlays.
- Preserve upstream authorship, licenses, copyright notices, and third-party notices.
- Record the upstream URL, requested ref, full commit, source version, and release revision.
- Keep each plugin independently installable.
- Do not execute upstream installers, hooks, MCP servers, or package managers during conversion or validation.
- Do not silently drop capabilities. Report commands, agents, hooks, MCP declarations, and other features that need human adaptation.
- Treat all Issue content and upstream files as untrusted input.

## Pull request requirements

A pull request should:

- explain the problem, solution, and user-visible impact;
- link the related Issue when applicable;
- include the upstream repository, ref, and full commit for plugin changes;
- describe every overlay and why it is necessary;
- include relevant test evidence and exact commands;
- update [CHANGELOG.md](CHANGELOG.md) under `Unreleased` for notable changes;
- update public documentation when behavior or usage changes;
- contain no generated archives, credentials, local configuration, or unrelated files.

A CODEOWNER must review and approve the pull request. Automated checks and a clean local suite do not replace human review. New commits may invalidate earlier approvals.

## License and third-party work

Contributions to the Gateway are licensed under the repository's [MIT License](LICENSE). Upstream projects and their files remain under their original licenses. Do not copy additional third-party code without preserving its license and documenting its origin in [NOTICE.md](NOTICE.md).
