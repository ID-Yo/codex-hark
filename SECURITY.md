# Security Policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub private vulnerability reporting (the **Security** tab of this repository, then **Report a vulnerability**). We aim to reply within 7 days and to publish a fix or mitigation within 30 days of a confirmed report.

## What the app can access

Codex Hark runs locally with your user rights. It reads the microphone, presses hotkeys and buttons in Codex Desktop, reads a Windows registry key and the local Codex thread-history database (read-only), and downloads one language model over HTTPS (checked by SHA256). Reports about any of these, or about the release file and its checksum, are in scope.
