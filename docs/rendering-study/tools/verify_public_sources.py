"""Check a pinned Lavatune checkout without changing its contents."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "f79516e82b9b6383ea1d169be2937c9ba6a5a93d"


def verify_source(source: Path, manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text())
    if manifest["commit"] != COMMIT:
        raise ValueError("The manifest does not describe the study's pinned commit")
    source = source.resolve()
    for record in manifest["files"]:
        path = (source / record["path"]).resolve()
        if not path.is_relative_to(source):
            raise ValueError("Manifest path escapes the source directory")
        data = path.read_bytes()
        blob_id = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if blob_id != record["sha"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError(f"Source mismatch: {record['path']}")
    return {"verified_files": len(manifest["files"]), "commit": COMMIT}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "_sources/lavatune-public")
    parser.add_argument("--manifest", type=Path, default=ROOT / "evidence/public-source-manifest.json")
    options = parser.parse_args()
    print(json.dumps(verify_source(options.source, options.manifest)))


if __name__ == "__main__":
    main()
