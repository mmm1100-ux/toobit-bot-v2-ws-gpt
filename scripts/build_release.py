from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
NAME = "toobit-bot-v2"


def main() -> None:
    DIST.mkdir(exist_ok=True)
    staging = DIST / NAME
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    for relative in ["app", "config.example.json", "pyproject.toml", "README.md"]:
        source = ROOT / relative
        target = staging / relative
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    archive = shutil.make_archive(str(DIST / NAME), "zip", DIST, NAME)
    print(archive)


if __name__ == "__main__":
    main()
