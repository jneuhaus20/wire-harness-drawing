#!/usr/bin/env python3
"""Regenerate every example's committed outputs and the tests' golden sheets after a deliberate change.

Usage:  python3 tools/regenerate_examples.py
Review the diff before committing: every change in it is a change to what the generator draws.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

repository = Path(__file__).resolve().parent.parent
generator = repository / "skills" / "wire-harness-drawing" / "scripts" / "harnessgen.py"
committed = ("checks.txt", "bom.csv", "wirelist.csv", "cables.csv", "harness.json", "pdf")


def main() -> int:
    for source in sorted((repository / "examples").glob("*/*.yaml")):
        name, folder = source.stem, source.parent
        with tempfile.TemporaryDirectory() as scratch:
            full, pinned = Path(scratch) / "full", Path(scratch) / "pinned"
            subprocess.run([sys.executable, str(generator), str(source), "-o", str(full)], capture_output=True)
            subprocess.run([sys.executable, str(generator), str(source), "-o", str(pinned), "--no-wireviz"], capture_output=True)
            for suffix in committed:
                if (full / f"{name}.{suffix}").exists():
                    shutil.copy(full / f"{name}.{suffix}", folder / f"{name}.{suffix}")
            for sheet in ("sheet1", "sheet2"):
                shutil.copy(pinned / f"{name}.{sheet}.svg", repository / "tests" / "golden" / f"{name}.{sheet}.svg")
            if name == "sensor-branch" and (full / f"{name}.wireviz.yaml").exists():
                shutil.copy(full / f"{name}.wireviz.yaml", repository / "tests" / "golden" / f"{name}.wireviz.yaml")
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
