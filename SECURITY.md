# Security Policy

## Supported versions

The Gateway is in its initial development stage. Security fixes are applied to the latest commit on `main` and, once releases exist, to the newest available Gateway release. Individual plugin adaptations use immutable upstream commits and must be updated through a reviewed pull request.

## Report a vulnerability

Do not disclose sensitive vulnerabilities in a public Issue, pull request, log, or proof-of-concept archive.

Use GitHub's private vulnerability reporting for this repository when available. Otherwise, contact the maintainer through the GitHub profile at https://github.com/endersonmenezes and avoid including exploit details or sensitive data until a private channel is established.

Include, when safe:

- the affected file, workflow, plugin, or release;
- the upstream repository and full commit;
- the impact and conditions required to trigger the issue;
- a minimal reproduction using non-sensitive fixtures;
- a proposed mitigation, if available.

The maintainer will triage the report and coordinate reproduction, remediation, and disclosure. Do not test against third-party systems or use real credentials.

## Security-sensitive areas

Reports involving the following areas are especially relevant:

- IssueOps command or expression injection;
- GitHub Actions permissions or untrusted-event handling;
- path traversal, symlink escapes, or malicious ZIP entries;
- submodule substitution or incorrect upstream provenance;
- execution of upstream installers, hooks, MCP servers, or scripts;
- release or asset replacement;
- accidental publication of credentials or private configuration.

Vulnerabilities originating in an upstream plugin should also be reported to that project's maintainers. The Gateway can pin a fixed revision or disable the affected adaptation after review.
