# Security Policy

## Supported versions

Security fixes are applied to the latest released version of Speech on the
`main` branch and published GitHub Releases.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Use one of these private channels instead:

1. GitHub private vulnerability reporting on this repository
   (Security tab → Advisories → Report a vulnerability), or
2. Email the maintainer if private reporting is unavailable.

Include:

- A clear description of the issue
- Steps to reproduce
- Impact assessment if known
- Whether a fix or workaround is already known

You should receive an acknowledgement within a few days. Please give us a
reasonable window to investigate and ship a fix before any public disclosure.

## What is in scope

- Remote code execution, privilege escalation, or sandbox escapes in Speech
- Credential, token, or private-data exposure through Speech code or releases
- Supply-chain issues in first-party packaging or update paths
- Abuse of the auto-update download/install flow

## What is out of scope

- Social engineering
- Denial of service against third-party services
- Issues that require physical access or an already-compromised user account
- Vulnerabilities only present in outdated dependencies when a fixed release
  already exists and has been adopted

## Hardening notes for this public repo

- Secrets such as API keys must never be committed (see `.gitignore` and
  `.env.example`)
- Installers and release assets are published via GitHub Releases with checksums
- Dependency and secret scanning alerts are enabled on GitHub
