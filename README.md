# Kimi Plugin Gateway

Kimi Plugin Gateway converts Claude plugins into independently installable Kimi Code plugins without forking the upstream projects. Each adaptation uses a real Git submodule pinned to a full commit, a generated Kimi manifest, reviewed overlays, and a standalone release archive.

> **Project status:** early development. The initial workflows and Impeccable adaptation are available for review, but runtime acceptance and the first releases are still being validated.

## Why a gateway?

- **No adaptation forks:** upstream projects remain Git submodules.
- **Reproducible provenance:** every plugin records its upstream URL, requested ref, full commit, source version, and Gateway revision.
- **Independent installation:** users install only the plugin they need.
- **Human approval:** IssueOps creates pull requests; CODEOWNERS review changes before release.
- **Reviewable adaptations:** Gateway-specific file changes live in overlays rather than inside upstream files.
- **Safer automation:** conversion does not execute upstream installers, hooks, MCP servers, or package managers.

## Available plugins

| Plugin | Upstream version | Upstream project | Upstream license |
| --- | --- | --- | --- |
| Impeccable | 4.10.0 | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | Apache-2.0 |

The initial Impeccable adaptation is pinned to commit `b49177d32788f2dc585c42831d845dacf1ebed2c` from tag `skill-v4.10.0`.

## Install a plugin

After the corresponding release is published, open the custom marketplace in Kimi Code:

```text
/plugins marketplace https://raw.githubusercontent.com/endersonmenezes/kimi-plugin-gateway/main/marketplace.json
```

Select only the plugin you want. Each marketplace entry points to a standalone ZIP release asset containing the manifest and the upstream files; no recursive clone is required.

You can also install a plugin ZIP directly:

```text
/plugins install https://github.com/endersonmenezes/kimi-plugin-gateway/releases/download/<plugin-tag>/<plugin-id>.zip
```

Run `/reload` or start a new session after installation. Use `/plugins info <id>` to inspect the manifest and diagnostics.

## Request a conversion or update

Open an issue using the [issue forms](https://github.com/endersonmenezes/kimi-plugin-gateway/issues/new/choose):

- **Convert a Claude plugin:** provide a public GitHub repository, a tag/branch/commit, and optionally a plugin ID and Claude manifest path.
- **Update a converted plugin:** provide an existing plugin ID and the new upstream ref.

The corresponding workflow validates the inputs, resolves the ref to a full commit, and opens a pull request. Invalid requests receive an issue comment with the failure and workflow run.

A conversion or update does not publish a release by itself. A maintainer must review and approve the pull request.

## Repository layout

```text
plugins/<id>/
  gateway.json          # Upstream and release metadata
  kimi.plugin.json      # Kimi plugin manifest
  overlays/             # Optional Gateway-maintained changes
  upstream/             # Real Git submodule at a pinned commit
scripts/gateway/        # Standard-library Python automation
.github/                # Issue Forms, workflows, and CODEOWNERS
marketplace.json        # Independent plugin sources
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for local commands and architecture details.

## Review and releases

- `.github/CODEOWNERS` assigns review to `@endersonmenezes`.
- Pull requests run the complete test suite and validate/package all plugins without publishing.
- Only merges to `main` or authorized manual dispatches can publish releases.
- Each changed plugin receives an independent ZIP and SHA-256 checksum.
- Tags follow `<id>-v<sourceVersion>-gateway.<revision>` and releases/assets are immutable.

### Required branch protection

CODEOWNERS alone does not enforce review. The repository administrator must configure `main` under **Settings → Branches** to require:

- a pull request before merging;
- at least one approval and CODEOWNER review;
- resolved conversations;
- required validation checks;
- stale approval dismissal after new commits;
- no direct pushes, including for administrators.

Until those settings are active, the repository does not fully enforce its review policy.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md), [DEVELOPMENT.md](DEVELOPMENT.md), and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Public-facing documentation, commit messages, pull requests, and review discussions use English.

Notable changes are tracked in [CHANGELOG.md](CHANGELOG.md). Security reports follow [SECURITY.md](SECURITY.md).

## License

Gateway code and original documentation are available under the [MIT License](LICENSE).

Third-party projects retain their original licenses. Impeccable is Apache-2.0 and its license and notices are preserved in the submodule and generated archives. See [NOTICE.md](NOTICE.md).
