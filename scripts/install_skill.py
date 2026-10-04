#!/usr/bin/env python3
"""Install the skill without overwriting a different local installation."""
import argparse
import hashlib
import os
import shutil
from pathlib import Path


def contents(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob("*") if p.is_file()
            and "__pycache__" not in p.parts and p.suffix != ".pyc"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path,
                        default=Path(os.environ.get("CODEX_HOME", str(Path.home()/".codex")))/"skills")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]/"skills"/"kaggle-compass"
    target = args.destination/"kaggle-compass"
    if target.exists():
        if contents(source) != contents(target):
            parser.error("existing skill differs; preserve it and install to another --destination")
        print("Skill already matches: " + str(target))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print("Installed skill: " + str(target))


if __name__ == "__main__":
    main()
