---
name: wire-harness-drawing
description: "Use when asked for a wire harness diagram or drawing: a manufacturing/formboard drawing package with lengths, BOM, wire list and checks, not a schematic."
license: MIT
---

# Wire harness drawing

"Wire harness diagram/drawing" means the **manufacturing document a shop builds and inspects the harness from**, not a schematic. A schematic shows electrical logic; a wiring diagram shows pin-to-pin connections with colours and gauges; the **harness (assembly/formboard) drawing** shows the physical harness laid flat: connectors, trunk, breakouts, branch lengths with tolerances, coverings, labels, ballooned find numbers, notes and a title block. A complete package is all of them, kept at the same revision, generated from one source.

## The package this skill produces

From one `harness.yaml`, `scripts/harnessgen.py` (in this skill's directory) writes:

| Output | What it is |
|---|---|
| `*.checks.txt` | Findings: ERROR / WARN / INFO. Exit code 1 on any ERROR, and every sheet then carries a red NOT FOR RELEASE mark. |
| `*.sheet1.svg` | Harness drawing: datum-to-breakout segment dimensions with tolerances, overall reference dimensions (REF, untoleranced) from the root connector to each leaf, bundle thickness by wire count, wire-colour fan at each connector (striped wires dashed in their stripe colour), splices (diamond), breakouts (circle), coverings (shaded, ballooned "AR"), labels with their position dimension, balloons with find numbers and contact quantities ("4X"), notes, revision block, title block, zone grid. Not to scale. |
| `*.sheet2.svg` and up | BOM (find no., qty or AR with computed length, TBD where a length runs through a TBD segment, unit, P/N, description, mfr, refs), wire list (from-to, BOM find number, strip length at each end, signal, gauge, colour, cut length, twist/cable), one table per connector (every cavity, empty ones marked). Flows onto extra sheets as needed. |
| last sheet | WireViz wiring diagram (connector pin tables, wires coloured and labelled; each twist group a named bundle, each harness cable drawn as that cable with its P/N and shield), embedded. |
| `*.pdf` | All sheets combined. |
| `*.bom.csv`, `*.wirelist.csv` | Same data for purchasing and cut/strip/crimp work (wire list includes routing path). |
| `*.wireviz.yaml`, `*.wiring.svg`, `*.wiring.png` | The generated WireViz input and WireViz's own render of it, in case someone wants to tweak the diagram by hand. |

## Workflow

1. **Collect inputs. Do not guess any of these; fetch datasheets.**
   - Every connector: designator, family, gender, P/N + manufacturer, cavity numbering (from the datasheet drawing, and which face it is viewed from), contact P/N and AWG range, strip length, backshell/accessories.
   - The connection source of truth (pin list, netlist, schematic). If the project already holds this as data, generate `harness.yaml` from that data rather than retyping it.
   - Routing: where the harness branches and each segment length (from CAD, a 3D model, or tape measure on the machine). Add service loop where a connector must be unplugged or the harness moves.
   - Wire: type (e.g. UL1007/1015, PTFE), gauge per current, colours (IEC 60757 two-letter codes: BK BN RD OG YE GN BU VT GY WH PK TQ; stripes concatenated, e.g. GNYE).
   - Coverings (braid, heat-shrink, spiral, conduit), labels, ties, and the IPC/WHMA-A-620 class.
2. **Write `harness.yaml`** (schema below). The generator reads YAML 1.2 booleans: only `true` and `false` are booleans, so a relay contact `NO` or a signal `OFF` stays text. Put the intended netlist in `expect.nets` independently of the wires, so the check compares two descriptions instead of one with itself.
3. **Check**: `python3 <skill-dir>/scripts/harnessgen.py harness.yaml --check-only`. Fix every ERROR. Read every WARN and either fix it or say why it stands.
4. **Generate**: `python3 <skill-dir>/scripts/harnessgen.py harness.yaml -o out/`.
5. **Look at it.** Render each sheet to PNG (`python3 -c "import cairosvg;cairosvg.svg2png(url='out/x.sheet1.svg',write_to='s1.png',output_width=1600)"`) and inspect: overlapping text, dimensions on the wrong side, balloons pointing at the wrong thing, a crowded branch. Adjust `layout` order/lengths or drawing data and regenerate. Never hand-edit the SVGs; they are regenerated.
6. **Deliver** the PDF plus CSVs, and state the dimensioning datum and tolerances used.

Setup (once per machine): `pip install pyyaml wireviz cairosvg pypdf` and Graphviz (`brew install graphviz` / `apt install graphviz`). Without WireViz/Graphviz the wiring-diagram sheet is skipped; without cairosvg/pypdf the PDF is skipped. Python 3.10+.

## Conventions the drawing follows (and where they come from)

- **Datum and length measurement** (external: L3 "Interpreting L3 Cable/Harness Drawings", doc 60102381; Altium/RapidHarness length model): lengths run from the connector datum to breakout centre or to the next connector datum. Industry uses either the mating face or the rear of the housing/backshell; this skill defaults to rear face and **prints the datum in note 2**. Set `drawing.datum` to change it. Breakouts are at the end of sleeving/jacket.
- **Tolerances** (convention, set per drawing): default ±5 to 300 mm, ±10 to 1000 mm, ±1 % above; in inches ±0.25 to 12 in, ±0.5 to 40 in, ±1 % above. Common in shop drawings but not mandated by IPC/WHMA-A-620; change `drawing.tolerance` to match the shop. Segment dimensions carry the tolerance and govern; overall dimensions are reference (REF), because toleranced overalls would contradict the stack-up of the segments.
- **Cut length** (consequence of the above): sum of segment lengths along the wire's route + `extra_per_wire` + each connector's `wire_allowance` (termination depth, service), rounded up to `round_to`. RapidHarness builds length the same way (insertion depth + backshell entry + bundle sum + extra length). Strip length is shown, not added.
- **Balloons / find numbers** (external, L3Harris): every BOM item is ballooned, referenced in a note, or listed in the wiring tables. Contacts carry an "nX" quantity at the connector; length items show "AR" (as required) with the computed length in brackets in the BOM.
- **Reference designators** (external, common practice/aerospace): P = plug (free connector), J = jack/receptacle (fixed), SP or BS = splice (don't mix), E = unterminated end/lug, W = wire, T = twist group.
- **Labels** (external, IPC/WHMA-A-620 §12.4 as cited by L3 60102381): at most 12 in (300 mm) from the end of a breakout or the rear of the connector accessory; text reads toward the connector; position dimensioned from datum to label centre.
- **Twists** (external): "TWIST INDICATED WIRES PER IPC/WHMA-A-620"; L3Harris examples are ≥4 twists/inch pairs, 3 triples, 2.5 quads. The default note cites the standard without a rate; add a rate in notes when the signal needs one. Twisting shortens a wire's reach, so cut lengths add `drawing.twist_takeup` (default 3 %, a shop convention; set it from your twist rate) over the segments the group runs through together, and a note states it.
- **Pinout view**: state whether a connector table is mating face or wire-insertion side (`view:`), because the two are mirror images.
- **Sealed connectors**: `sealed: true` makes empty cavities show "(seal)" and adds an INFO line for sealing plugs.
- **Not to scale**: harness drawings are normally NTS; dimensions govern. A 1:1 nailboard print is a separate step this tool does not do (see Limits).

## Checks performed

Values of the wrong kind (a gauge with no unit, a length that is not a number, `round_to` not above 0, a wire missing an end, a covering on a segment the layout lacks: each is reported and left out); drawing does not fit sheet 1 (anything off the sheet or on the notes, title, revision or release-mark blocks); `drawing.units` other than mm or in; undefined connector or pin; duplicate wire ids; more than one wire in a cavity without a splice or `double_crimp`; wire gauge outside the connector's contact `awg` range; signal name differs from the pin label at either end; labelled pins left unwired; splices with fewer than 3 wires; twist groups with one wire or diverging ends; cable with more wires than conductors; layout not a tree (loops, disconnected nodes, segment not carrying wires, connector not placed); **netlist comparison** against `expect.nets`: opens (net split or member not wired), shorts (two expected nets joined), unexpected members, and wired connections no expected net claims. Splices and connector `loops` are merged into nets. Also: coverings and labels that name an unknown item or node; a label beyond its segment, or farther than 300 mm (12 in) from its connector; a label item whose qty differs from the labels using it; a negative segment length; a tolerance table with no `upto: null` row; a wire end with no pin on a multi-pin connector; a gauge not in AWG on a connector with an `awg` range (WARN, unchecked).

## harness.yaml schema

```yaml
drawing:
  title: str            number: str      rev: str      date: str
  drawn_by: str         checked_by: str  units: mm | in   # unit of every length entered; the BOM buys in m or ft
  ipc_class: 1|2|3                       # default 2
  datum: "connector rear face"           # printed in note 2
  tolerance: [{upto: 300, tol: 5}, {upto: 1000, tol: 10}, {upto: null, tol: "1%"}]
  round_to: 5           extra_per_wire: 0      loopback_length: 100   # mm defaults; in: 0.25, 0, 4
  twist_takeup: "3%"    # added to twisted wires over their shared run
  wire_type: "UL1007 hook-up wire"       # BOM description prefix
  notes: [str, ...]                      # appended after the standard notes
  revisions: [{rev, desc, date, by}]

connectors:
  P1:                                    # designator
    label: "TO CONTROLLER"               # shown under the designator and in tables
    type: DE-9     subtype: "plug, male"  desc: optional BOM text
    pn: str  manufacturer: str
    pincount: 9 | pins: [A, B, ...]
    pinlabels: [GND, +5V, ...] | {1: GND, ...}
    contact: {pn, desc, manufacturer, spare: 0}   # qty = pins used + spare; a double_crimp pin takes one contact
    accessories: [{pn, desc, manufacturer, qty}]  # backshell, seals, caps; a block of N single-way housings lists the housing here, qty N
    awg: [20, 28]          # contact range, checked
    wire_allowance: 0      # length added to cut length at this end
    strip: 3               # length, written to wirelist.csv
    sealed: false   view: "mating face"   double_crimp: [pin, ...]   loops: [[1, 2]]
    hide_unused: false     # hide empty pins in the WireViz diagram
    mpn: str   notes: str  # passed through to the WireViz diagram
  SP1: {type: splice, desc: str, pn: str}   # wires end at "SP1"

cables:                    # optional multi-conductor cables
  C1: {desc, pn, manufacturer, conductors: 4}

wires:                     # the from-to list, one row per conductor
  - {id: W1, from: "P1:1", to: "J1:1", signal: GND, gauge: "22 AWG", color: BK,
     twist: T1, cable: C1, length: (override), pn, type, note,
     signal_differs_ok: true}   # accept a signal name that differs from the pin label
    # gauge TBD or color omitted while undecided: the diagram shows a wire count, no stand-in colour

layout:
  root: P1                 # leftmost connector; dimensions are measured from it
  segments:                # tree of bundle segments: [from, to, length]
    - [P1, B1, 300]        # nodes that are not connectors are breakouts
    - [B1, J2, TBD]        # length not known yet: prints TBD, drawn at a stand-in length, adds a DO NOT CUT note
  coverings:
    - {item: SLV1, segments: [P1-B1, B1-B2]}
      # optional: display_color: "#9aa7b8", display_width: 16 (how the covering is shaded on the sheet)
  labels:
    - {at: P1, text: "P1 CTRL", distance: 50, item: LBL}   # distance defaults to 50 mm / 2 in

items:                     # everything else on the BOM
  - {id: SLV1, desc: str, pn: str, manufacturer: str, qty: AR|number, unit: m|EA, refs: [P1, ...]}
  # qty AR on a covering item is computed from its segments; labels count themselves

expect:
  nets: {GND: ["P1:1", "J1:1"], ...}
```

## Limits (say these when they matter)

- Connector bodies are generic boxes. If a face view matters (keying, clocking), add a note and the manufacturer's face drawing as a separate detail; do not invent one.
- Layout is automatic: the farthest-reaching child continues the trunk, other branches alternate above and below. Past ~10 leaves or very uneven lengths the drawing stops fitting the sheet, which the checks report as an ERROR; split into sub-harnesses joined at an in-line connector.
- Shields are modelled as a wire (drain) plus a covering item; overbraid termination details go in notes.
- No 1:1 formboard/nailboard output. Lay out on the board from the dimensions, or add a to-scale mode when someone needs it.
