# Contributing

Lavatune is a working codename. Small, focused changes are easier to review while the product identity and motion language are still settling.

## Development setup

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
ruff check .
python scripts/benchmark.py --frames 20
```

Use `lavatune --demo` when developing without an audio server. Tests must not require a live audio device, desktop session, or network connection.

## Changes

- Keep runtime dependencies minimal and justify any new dependency.
- Preserve fixed subprocess argument lists; never interpolate config into a shell command.
- Sanitize external text before displaying it in the terminal.
- Add focused tests for behavior changes and resize-sensitive rendering.
- Keep personal i3 configuration and machine-specific audio sources out of the core package.

Before opening an issue or attaching a screenshot, redact media titles, usernames, filesystem paths, and audio device names that you do not intend to publish.

## Tool-assisted contributions

AI-assisted contributions are welcome when the contributor remains accountable for them. Disclose substantial agent or model use in the pull request, read the resulting diff, run the relevant tests, and be able to explain the behavior being changed. Please do not submit a raw generated patch that you have not exercised or reviewed.

Authorship here is about direction, judgment, review, and responsibility, not whether every character was entered manually. The initial project's own use of Codex is documented in [`AUTHORS.md`](AUTHORS.md).
