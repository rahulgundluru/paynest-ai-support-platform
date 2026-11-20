"""Fetch and verify the PayNest source case data.

The source repository (https://github.com/niti007/paynest-support-discovery) is the
read-only origin of every dataset used by this platform. Its contents are NOT committed
to this repository (no upstream licence; this repository is public). Instead:

  python scripts/source_data.py fetch    # clone the pinned upstream commit into data/source/
  python scripts/source_data.py verify   # check data/source/ against data/source_manifest.json
  python scripts/source_data.py manifest # (maintainers) regenerate the manifest from data/source/

The manifest records the upstream URL, pinned commit and a SHA-256 for every file, so
every downstream record stays traceable to an exact source byte sequence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "source"
MANIFEST = ROOT / "data" / "source_manifest.json"
UPSTREAM_URL = "https://github.com/niti007/paynest-support-discovery.git"
UPSTREAM_COMMIT = "502e718"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def _files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*") if p.is_file() and ".git" not in p.relative_to(base).parts)


def build_manifest() -> dict:
    if not SOURCE_DIR.is_dir():
        raise SystemExit(f"{SOURCE_DIR} does not exist; run 'fetch' first")
    entries = [
        {"path": p.relative_to(SOURCE_DIR).as_posix(), "bytes": p.stat().st_size, "sha256": _sha256(p)}
        for p in _files(SOURCE_DIR)
    ]
    return {
        "upstream_url": UPSTREAM_URL.removesuffix(".git"),
        "upstream_commit": UPSTREAM_COMMIT,
        "note": "Simulated teaching data. Treat as confidential. Not committed to this repository.",
        "excluded": ["trainer/ (answer key; never fetched or read)"],
        "files": entries,
    }


def verify() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = {e["path"]: e["sha256"] for e in manifest["files"]}
    problems: list[str] = []
    for rel, sha in expected.items():
        path = SOURCE_DIR / rel
        if not path.is_file():
            problems.append(f"missing: {rel}")
        elif _sha256(path) != sha:
            problems.append(f"hash mismatch: {rel}")
    if SOURCE_DIR.is_dir():
        for path in _files(SOURCE_DIR):
            rel = path.relative_to(SOURCE_DIR).as_posix()
            if rel not in expected:
                problems.append(f"unexpected file: {rel}")
    for line in problems:
        print(line)
    print(f"verified {len(expected) - len([p for p in problems if not p.startswith('unexpected')])}/{len(expected)} files")
    return 1 if problems else 0


def fetch() -> int:
    if SOURCE_DIR.exists() and any(SOURCE_DIR.iterdir()):
        print(f"{SOURCE_DIR} already populated; verifying instead")
        return verify()
    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "upstream"
        subprocess.run(["git", "clone", "--quiet", UPSTREAM_URL, str(clone)], check=True)
        subprocess.run(["git", "-C", str(clone), "checkout", "--quiet", UPSTREAM_COMMIT], check=True)
        SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        for path in _files(clone):
            rel = path.relative_to(clone)
            if rel.parts[0] == "trainer":
                continue
            target = SOURCE_DIR / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return verify()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["fetch", "verify", "manifest"])
    args = parser.parse_args()
    if args.command == "manifest":
        MANIFEST.write_text(json.dumps(build_manifest(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {MANIFEST.relative_to(ROOT)}")
        return 0
    return fetch() if args.command == "fetch" else verify()


if __name__ == "__main__":
    sys.exit(main())
