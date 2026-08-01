# Security Policy

## Supported versions

Until the first stable release, security fixes are made on the latest alpha release and the default branch only.

## Reporting a vulnerability

Use GitHub private vulnerability reporting from the repository's **Security** tab. Do not open a public issue for a suspected vulnerability or include private media metadata, device names, or filesystem paths in a report.

If private vulnerability reporting is unavailable, contact a maintainer privately through the contact method on their GitHub profile. Include affected versions, reproduction steps, impact, and a proposed mitigation when possible.

## Security properties

Lavatune is designed to remain local and easy to audit:

- no network access or telemetry
- no daemon, service installation, or privilege escalation
- no shell interpolation or dynamic plugin loading
- no downloaded themes, models, or assets
- structured TOML parsing with unknown-key rejection
- fixed subprocess argument lists
- bounded media fields and backend diagnostics

Lavatune starts local programs only when their feature is used:

- `pw-cat`, `parec`, or `ffmpeg` for system-audio capture
- `playerctl` for optional MPRIS media metadata

These programs are executed directly with explicit argument arrays. User-supplied audio source names remain one argument and are never evaluated by a shell.

## Trust boundaries

Lavatune processes data from several local trust boundaries:

- PCM bytes and diagnostics produced by the selected audio backend
- player names, status, titles, artists, and URLs returned by MPRIS through `playerctl`
- terminal keyboard, mouse, resize, and focus events
- user-selected TOML configuration files

Media fields are length-limited and stripped of terminal controls, bidirectional controls, and invisible formatting characters before display. This reduces terminal injection and visual-spoofing risk, but a compromised terminal emulator, audio server, or same-user desktop session remains outside Lavatune's protection boundary.

Focus-loss exit depends on terminal focus-reporting escape sequences. A terminal or multiplexer that does not forward these events may prevent blur-exit from firing.

## Privacy

Lavatune does not record or transmit audio. It analyzes a live monitor stream in memory. Media titles and artists are displayed locally, but screenshots, terminal recordings, issue reports, and logs created by the user can expose them. Redact this material before sharing it.

## Non-goals

- hardened process sandboxing
- kernel-level audio isolation
- protection from a malicious same-user audio server, media player, or terminal emulator
- secure deletion of terminal scrollback or third-party recordings
