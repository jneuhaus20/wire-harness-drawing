#!/usr/bin/env python3
"""Build the project site: the pages in site/, the skill's explorer component, and every example generated from its source.

Usage:  python3 tools/build_site.py [--output _site] [--no-wireviz]

The page's examples are filled in at build time from what the generator wrote:
  <span data-bind="split-cable.cables.W5.cut_length"></span>   a value from that example's model
  <pre data-include="examples/two-wire/two-wire.yaml"></pre>    a built file's text
  <wire-harness-explorer data-model="split-cable">              that example's model, inline
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

repository = Path(__file__).resolve().parent.parent
skill_directory = repository / "skills" / "wire-harness-drawing"
generator = skill_directory / "scripts" / "harnessgen.py"


# The site holds no copy of anything in the repository: its pages come from site/, the
# component from the skill, and each example's package from running the generator on its source.
def main(arguments: list[str]) -> int:
    """Build the site into the output directory; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=repository / "_site", help="directory to build into (default: _site)")
    parser.add_argument("--no-wireviz", action="store_true", help="leave out the wiring-diagram sheets")
    options = parser.parse_args(arguments)
    if options.output.exists():
        shutil.rmtree(options.output)
    shutil.copytree(repository / "site", options.output)
    shutil.copy(skill_directory / "explorer" / "wire-harness-explorer.js", options.output / "wire-harness-explorer.js")
    for source in sorted((repository / "examples").glob("*/*.yaml")):
        if not generate_example(source, options.output / "examples" / source.stem, options.no_wireviz):
            return 1
    for page in options.output.glob("*.html"):
        page.write_text(filled_page(page.read_text(), options.output))
    print(options.output)
    return 0


def generate_example(source: Path, target: Path, no_wireviz: bool) -> bool:
    """Generate one example's package beside a copy of its source; False if the generator crashed.

    An example may be one that fails its checks on purpose, so only a crash stops the build."""
    target.mkdir(parents=True)
    shutil.copy(source, target / source.name)
    command = [sys.executable, str(generator), str(source), "-o", str(target)] + (["--no-wireviz"] if no_wireviz else [])
    # An empty model cache: the published site never carries a maker's model from this machine's cache.
    with tempfile.TemporaryDirectory() as cache:
        process = subprocess.run(command, capture_output=True, text=True, env={**os.environ, "WIRE_HARNESS_CACHE": cache})
    if "Traceback" in process.stderr:
        print(process.stderr, file=sys.stderr)
        return False
    return True


def filled_page(page: str, site: Path) -> str:
    """The page with every binding, include and explorer filled from the built examples."""
    page = re.sub(r'(data-bind="([^"]+)"[^>]*>)[^<]*(<)',
                  lambda match: match[1] + html.escape(str(bound_value(site, match[2]))) + match[3], page)
    page = re.sub(r'(data-include="([^"]+)"[^>]*>)(</pre>)',
                  lambda match: match[1] + html.escape((site / match[2]).read_text(), quote=False) + match[3], page)
    return re.sub(r'(<wire-harness-explorer[^>]*data-model="([^"]+)"[^>]*>)',
                  lambda match: match[1] + inline_model(site, match[2]), page)


def example_model(site: Path, name: str) -> dict:
    """An example's built harness model."""
    return json.loads((site / "examples" / name / f"{name}.harness.json").read_text())


def bound_value(site: Path, binding: str) -> object:
    """The value a binding names: the example, then keys, list indexes or the id of a list item."""
    name, *path = binding.split(".")
    value = example_model(site, name)
    for key in path:
        if isinstance(value, list):
            value = value[int(key)] if key.isdigit() else next(item for item in value if item.get("id") == key)
        else:
            value = value[key]
    return value


def inline_model(site: Path, name: str) -> str:
    """An example's model as an inline JSON script, with every "</" escaped so it cannot close the script."""
    text = json.dumps(example_model(site, name), separators=(",", ":")).replace("</", "<\\/")
    return f'<script type="application/json">{text}</script>'


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
