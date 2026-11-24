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

[`SKILL.md`](SKILL.md) holds the input schema, the checks, the drafting conventions the drawing follows, and the limits.

## Why a generator

[WireViz](https://github.com/wireviz/WireViz) is the established open-source tool for the wiring diagram and its BOM. It draws no physical layout: no branch lengths, breakouts or formboard view. The tools that do draw one are commercial GUI packages (RapidHarness, Altium Harness Design, Zuken E3.series, Siemens Capital), which a script cannot drive. This generator draws the layout itself, hands the wiring diagram to WireViz, and builds every sheet and table from the same source file so they cannot disagree.

## Install as a skill

```bash
git clone https://github.com/jneuhaus20/wire-harness-drawing ~/.claude/skills/wire-harness-drawing
```

```bash
pip install pyyaml wireviz cairosvg pypdf
```

```bash
brew install graphviz
```

WireViz and Graphviz draw the wiring-diagram sheet; cairosvg and pypdf build the PDF. The generator skips either step when its tools are missing and says so.

## Run it directly

```bash
python3 scripts/harnessgen.py example/example.yaml --check-only
```

```bash
python3 scripts/harnessgen.py example/example.yaml -o out/
```

The example leaves two pins unwired on purpose, so the check reports two errors and exits 1.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

The tests regenerate the example and compare it with the committed outputs in `example/` and the golden sheets in `tests/golden/`. After a deliberate change to the generator's output, regenerate those files and review the diff.
