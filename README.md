# wire-harness-drawing

A Claude skill that turns one YAML description of a wire harness into the drawing package a shop builds and inspects from: a formboard-style harness drawing, bill of materials, wire list, connector tables, a wiring diagram, and a check report.

[`example/example.pdf`](example/example.pdf) is the package generated from [`example/example.yaml`](example/example.yaml).

## What it writes

| File | Contents |
|---|---|
| `*.checks.txt` | Findings from the checks, including a comparison of the wiring against an independently stated netlist. Exit code 1 on any ERROR. |
| `*.sheet1.svg` | Harness drawing: branch lengths with tolerances, breakouts, splices, coverings, labels, ballooned find numbers, notes, title block. |
| `*.sheet2.svg` and up | BOM, wire list with cut lengths, one table per connector. |
| last sheet | Wiring diagram drawn by [WireViz](https://github.com/wireviz/WireViz). |
| `*.pdf` | All sheets. |
| `*.bom.csv`, `*.wirelist.csv` | The same data for purchasing and for cut, strip and crimp work. |
| `*.harness.json` | The harness model for the interactive 2D/3D explorer, a single dependency-free web component in [`skills/wire-harness-drawing/explorer/`](skills/wire-harness-drawing/explorer/). |

[`SKILL.md`](skills/wire-harness-drawing/SKILL.md) holds the input schema, the checks, the drafting conventions the drawing follows, and the limits.

## Why a generator

[WireViz](https://github.com/wireviz/WireViz) is the established open-source tool for the wiring diagram and its BOM. It draws no physical layout: no branch lengths, breakouts or formboard view. The tools that do draw one are commercial GUI packages (RapidHarness, Altium Harness Design, Zuken E3.series, Siemens Capital), which a script cannot drive. This generator draws the layout itself, hands the wiring diagram to WireViz, and builds every sheet and table from the same source file so they cannot disagree.

## Install

**Claude Code** (CLI, IDE, or the desktop app's Code tab). Add this repository as a plugin marketplace and install the plugin:

```text
/plugin marketplace add jneuhaus20/wire-harness-drawing
```

```text
/plugin install wire-harness-drawing@wire-harness-drawing
```

To pick up new releases on their own, turn on auto-update for the `wire-harness-drawing` marketplace under `/plugin` > Marketplaces. Claude Code leaves auto-update off for marketplaces outside Anthropic's. Without it, `/plugin marketplace update wire-harness-drawing` updates on demand.

**Claude Desktop chat and claude.ai.** Download `wire-harness-drawing-<version>.zip` from the [latest release](https://github.com/jneuhaus20/wire-harness-drawing/releases/latest) and upload it under Customize > Skills. These apps install skills only from an uploaded zip and do not update them, so upload each new release to update.

**Dependencies.** The generator needs Python 3.10 or later and PyYAML. The optional tools are:

```bash
pip install pyyaml wireviz cairosvg pypdf
```

```bash
brew install graphviz
```

WireViz and Graphviz draw the wiring-diagram sheet; cairosvg and pypdf build the PDF. The generator skips either step when its tools are missing and says so.

## Run it directly

```bash
python3 skills/wire-harness-drawing/scripts/harnessgen.py example/example.yaml --check-only
```

```bash
python3 skills/wire-harness-drawing/scripts/harnessgen.py example/example.yaml -o out/
```

The example passes every check, so the check prints `OK     no findings` and exits 0.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

The tests need Python 3.11 or later. They regenerate the example and compare it with the committed outputs in `example/` and the golden sheets in `tests/golden/`. After a deliberate change to the generator's output, regenerate those files and review the diff.

## Releasing

1. Set the new version in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json). Claude Code offers an update only when this version changes.
2. Commit, then tag the commit `v` plus that version (for example `v1.1.0`) and push the tag.
3. The release workflow runs the tests, builds `wire-harness-drawing-<version>.zip` with [`tools/build_release.py`](tools/build_release.py), and publishes a GitHub release with the zip attached. It refuses a tag that does not match the version.

To build the zip locally: `python3 tools/build_release.py` writes it to `dist/`.

## Licence

[MIT](LICENSE).
