## Summary

Describe the problem, the change, and the user-visible result.

## Related issues

Link related Issues using `Closes #123` when appropriate.

## Changes

- <describe the main changes>

## Provenance and compatibility

For plugin additions or updates, include:

- Upstream repository and requested ref:
- Full upstream commit:
- Source version and Gateway revision:
- New or changed overlays and why they are needed:

State whether hooks, MCP servers, commands, agents, or other capabilities require follow-up.

## Validation

List the exact commands and results. Include real Kimi CLI verification when changing installation or runtime behavior.

```text
PYTHONPATH=scripts python3 -m unittest discover -s tests -v
```

## Checklist

- [ ] Tests and documentation cover the change.
- [ ] `CHANGELOG.md` is updated for notable changes.
- [ ] Public-facing contribution content is in English.
- [ ] Upstream files are unchanged; adaptations use overlays.
- [ ] Upstream licenses and notices are preserved.
- [ ] No upstream code, installer, hook, or MCP server was executed.
- [ ] No generated archives, credentials, or local configuration are included.
- [ ] The change is ready for CODEOWNER review.
