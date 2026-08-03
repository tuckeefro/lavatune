#!/usr/bin/env python3
"""Reject incomplete or contaminated Python release archives."""

from __future__ import annotations

import argparse
import ast
import email.parser
import re
import sys
import tarfile
import zipfile
from pathlib import Path


FORBIDDEN_PARTS = {
    ".env",
    ".git",
    "__pycache__",
    "artifacts",
    "build",
    "tools",
}
REQUIRED_SDIST_SUFFIXES = {
    "AUTHORS.md",
    "README.md",
    "SECURITY.md",
    "docs/ARCHITECTURE.md",
    "docs/DESIGN.md",
    "docs/MACOS.md",
    "scripts/benchmark.py",
    "scripts/benchmark_render.py",
    "scripts/verify_dist.py",
}


def read_version(path: Path) -> str:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise ValueError(f"No literal __version__ assignment found in {path}")


def _normalized_distribution_version(version: str) -> str:
    match = re.fullmatch(r"(.+?)(a|b|rc)(\d*)$", version)
    if not match:
        return version
    base, pre_tag, pre_number = match.groups()
    if pre_number:
        return version
    return f"{base}{pre_tag}0"


def _contaminated(name: str) -> bool:
    parts = set(Path(name).parts)
    return bool(parts & FORBIDDEN_PARTS) or name.endswith((".pyc", ".log", ".local.toml"))


def verify_sdist(path: Path) -> list[str]:
    errors: list[str] = []
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
    contaminated = [name for name in names if _contaminated(name)]
    if contaminated:
        errors.append(f"{path.name}: forbidden entries: {', '.join(contaminated)}")
    for suffix in sorted(REQUIRED_SDIST_SUFFIXES):
        if not any(name.endswith(f"/{suffix}") for name in names):
            errors.append(f"{path.name}: missing {suffix}")
    return errors


def verify_wheel(path: Path, expected_version: str) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            return [f"{path.name}: expected one METADATA file"]
        metadata = email.parser.Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
    contaminated = [name for name in names if _contaminated(name)]
    if contaminated:
        errors.append(f"{path.name}: forbidden entries: {', '.join(contaminated)}")
    if metadata.get("Name") != "lavatune":
        errors.append(f"{path.name}: unexpected package name {metadata.get('Name')!r}")
    if metadata.get("Version") != expected_version:
        errors.append(
            f"{path.name}: metadata version {metadata.get('Version')!r} != {expected_version!r}"
        )
    if metadata.get("Requires-Python") != ">=3.11":
        errors.append(f"{path.name}: unexpected Requires-Python value")
    if "lavatune/doctor.py" not in names:
        errors.append(f"{path.name}: missing lavatune/doctor.py")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    version_file = Path(__file__).parents[1] / "src" / "lavatune" / "__init__.py"
    version = read_version(version_file)
    distribution_version = _normalized_distribution_version(version)

    wheels = sorted(args.directory.glob("lavatune-*.whl"))
    sdists = sorted(args.directory.glob("lavatune-*.tar.gz"))
    expected_wheel = args.directory / f"lavatune-{distribution_version}-py3-none-any.whl"
    expected_sdist = args.directory / f"lavatune-{distribution_version}.tar.gz"
    errors: list[str] = []
    if expected_wheel not in wheels:
        errors.append(f"missing {expected_wheel.name}")
    if expected_sdist not in sdists:
        errors.append(f"missing {expected_sdist.name}")
    if expected_sdist.exists():
        errors.extend(verify_sdist(expected_sdist))
    if expected_wheel.exists():
        errors.extend(verify_wheel(expected_wheel, distribution_version))
    if errors:
        print("Distribution verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Verified {expected_sdist.name} and {expected_wheel.name}")
    if distribution_version != version:
        print(f"Normalized pre-release version: {version} -> {distribution_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
