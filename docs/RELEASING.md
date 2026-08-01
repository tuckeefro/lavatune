# Releasing

Lavatune releases are built by GitHub Actions from an exact version tag. PyPI publishing is not enabled yet.

## Release gate

1. Update `CHANGELOG.md` and move relevant entries out of `Unreleased` when appropriate.
2. Change `src/lavatune/__init__.py::__version__`. Packaging reads this value directly; `pyproject.toml` does not duplicate it.
3. Run the source checks and inspect the real TUI in silence, speech, bass, music, and transient cases.
4. Merge through a green CI run on `main`.
5. Create an annotated tag exactly matching `v` plus the PEP 440 package version.

```bash
python -m unittest discover -s tests -v
ruff check .
python -m build
twine check dist/*
python scripts/verify_dist.py dist
python scripts/benchmark.py
```

Exercise the installed artifact separately:

```bash
python -m venv /tmp/lavatune-release-check
/tmp/lavatune-release-check/bin/pip install dist/*.whl
/tmp/lavatune-release-check/bin/lavatune --version
/tmp/lavatune-release-check/bin/lavatune --doctor
/tmp/lavatune-release-check/bin/lavatune --demo
```

## Tag and GitHub release

For package version `0.1.0a1`, use tag `v0.1.0a1`:

```bash
git switch main
git pull --ff-only
git tag -a v0.1.0a1 -m "Lavatune 0.1.0a1"
git push origin v0.1.0a1
```

`.github/workflows/release.yml` then:

1. verifies the tag against the package version
2. runs the complete test suite
3. builds the wheel and source archive with the tagged commit time
4. validates archive metadata and rejects local/generated content
5. installs and imports the built wheel
6. writes `SHA256SUMS`
7. creates a GitHub prerelease and attaches all three files

The workflow is safe to rerun: an existing release receives replacement artifacts instead of creating a duplicate release.

## Verification

Download all attached files into one directory and run:

```bash
sha256sum -c SHA256SUMS
```

The checksum proves which bytes GitHub served. Rebuilding with the same `SOURCE_DATE_EPOCH` is intended to reduce archive timestamp drift, but bit-for-bit reproducibility is not claimed until it is independently verified on multiple builders.

## PyPI

Do not add a long-lived PyPI token to repository secrets. When PyPI distribution is wanted, configure a Trusted Publisher for this repository and a dedicated GitHub environment, then add a separate publish job requiring that environment.
