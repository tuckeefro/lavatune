# Releasing

## Release gate

1. Confirm the changelog describes the release.
2. Run the full test and lint suite.
3. Build both distributions in an isolated environment.
4. Install the wheel into a second clean environment.
5. Exercise `lavatune --help` and `lavatune --demo` in a terminal.
6. Review the repository for generated artifacts, local configuration, logs, media titles, device names, and credentials.
7. Confirm GitHub CI passes with read-only permissions.

```bash
python -m unittest discover -s tests -v
ruff check .
python -m build
twine check dist/*
python -m venv /tmp/lavatune-release-check
/tmp/lavatune-release-check/bin/pip install dist/*.whl
/tmp/lavatune-release-check/bin/lavatune --help
```

## Versioning

Use Semantic Versioning for tags and PEP 440 for Python package versions. For example, tag `v0.1.0-alpha.1` uses package version `0.1.0a1`. Keep `pyproject.toml` and `src/lavatune/__init__.py` synchronized until versioning is automated.

## GitHub release

Create the tag only after CI passes. Attach the wheel and source distribution generated from that exact tag. PyPI publication is a separate decision and should use GitHub trusted publishing rather than a long-lived API token.
