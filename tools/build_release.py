#!/usr/bin/env python3
"""Build the release zip of the wire-harness-drawing skill: the skill folder at the zip's root, ready to upload to Claude.

Usage:  python3 tools/build_release.py [--output dist] [--tag vX.Y.Z]
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

repository = Path(__file__).resolve().parent.parent
skill_name = "wire-harness-drawing"
skill_directory = repository / "skills" / skill_name
# The frontmatter keys claude.ai accepts in an uploaded skill; it rejects the upload for any other.
uploadable_frontmatter_keys = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
description_limit = 200
# A fixed timestamp, so the same sources always build the same zip.
entry_timestamp = (1980, 1, 1, 0, 0, 0)


def plugin_version() -> str:
    return json.loads((repository / ".claude-plugin" / "plugin.json").read_text())["version"]


def frontmatter(skill_document: str) -> dict[str, str]:
    """The key-value pairs between the opening --- lines of a SKILL.md."""
    block = re.match(r"---\n(.*?)\n---\n", skill_document, re.S)
    if not block:
        return {}
    return {key.strip(): value.strip().strip('"') for key, value in (entry.split(":", 1) for entry in block.group(1).splitlines())}


# Everything claude.ai checks when a skill zip is uploaded, checked before the zip is built.
def upload_problems(skill_document: str) -> list[str]:
    """Why claude.ai would refuse this SKILL.md; empty when it would accept it."""
    metadata = frontmatter(skill_document)
    problems = [f"SKILL.md frontmatter key '{key}' is not accepted by claude.ai"
                for key in sorted(set(metadata) - uploadable_frontmatter_keys)]
    if metadata.get("name") != skill_name:
        problems.append(f"SKILL.md name '{metadata.get('name')}' differs from the folder name '{skill_name}'")
    if len(metadata.get("description", "")) > description_limit:
        problems.append(f"SKILL.md description is {len(metadata['description'])} characters; claude.ai allows {description_limit}")
    return problems


def release_files() -> list[tuple[Path, str]]:
    """Each file of the release with its path inside the zip, the licence included."""
    files = [(path, f"{skill_name}/{path.relative_to(skill_directory).as_posix()}")
             for path in sorted(skill_directory.rglob("*"))
             if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc" and path.name != ".DS_Store"]
    return files + [(repository / "LICENSE", f"{skill_name}/LICENSE")]


def write_zip(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in release_files():
            entry = zipfile.ZipInfo(name, entry_timestamp)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (0o755 if path.name == "harnessgen.py" else 0o644) << 16
            archive.writestr(entry, path.read_bytes())


# A release tag must name the version in plugin.json, because Claude Code updates a plugin
# when that version changes.
def main(arguments: list[str]) -> int:
    """Check the skill and the tag, then build the zip; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=repository / "dist", help="directory for the zip (default: dist)")
    parser.add_argument("--tag", help="the release tag; it must be v followed by the plugin.json version")
    options = parser.parse_args(arguments)
    version = plugin_version()
    if options.tag is not None and options.tag != f"v{version}":
        print(f"tag {options.tag} does not match plugin.json version {version}; tag the release v{version}", file=sys.stderr)
        return 2
    problems = upload_problems((skill_directory / "SKILL.md").read_text())
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    options.output.mkdir(parents=True, exist_ok=True)
    zip_path = options.output / f"{skill_name}-{version}.zip"
    write_zip(zip_path)
    print(zip_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
