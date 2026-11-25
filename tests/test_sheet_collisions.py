"""Sheet 1 draws nothing over anything else: text, balloons, bodies, bundles and dimension lines each keep
their own place, and a drawing that cannot be laid out so is an ERROR, not a sheet that looks finished."""
import tempfile
import unittest
from pathlib import Path

from tests.generator import example_names, examples_directory

from harness.formboard import SheetLayout, sheet_collisions  # noqa: E402  (tests.generator puts scripts/ on the path)
from harness.package import analyse
from harness.source import load_source


def analysed(source_text: str):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "harness.yaml"
        path.write_text(source_text)
        return analyse(load_source(path))


def terminals(names: list[str]) -> str:
    return "".join(f"  {name}: {{type: Terminal, pn: T-1, pincount: 1, label: DRIVE {name}, double_crimp: [1]}}\n" for name in names)


# Shaped like the gantry run's drive power harness: the root is a breakout with six short legs to
# drive terminals, a second breakout with two more, then a bulkhead, a PE stud and two bus positions.
power_harness = ("drawing: {title: DRIVE POWER, number: T-30, rev: A}\nconnectors:\n"
                 + terminals(["TB1", "TB2", "TB3", "TB4", "TB5", "TB6", "TB7"])
                 + """  J1: {type: Powerpole, pn: PP-4, pincount: 4, label: PWR BULKHEAD}
  RL1: {type: Ring lug, pn: RL-1, pincount: 1, label: PE STUD, double_crimp: [1]}
  PP1: {type: Powerpole, pn: PP-1, pincount: 1, label: LS BUS, POSITION 2}
  PP2: {type: Powerpole, pn: PP-1, pincount: 1, label: N BUS, POSITION 2}
wires:
  - {id: W1, from: "TB1:1", to: "J1:1", gauge: 16 AWG, color: RD}
  - {id: W2, from: "TB2:1", to: "J1:2", gauge: 16 AWG, color: BK}
  - {id: W3, from: "TB3:1", to: "J1:3", gauge: 16 AWG, color: WH}
  - {id: W4, from: "TB4:1", to: "RL1:1", gauge: 16 AWG, color: GNYE}
  - {id: W5, from: "TB7:1", to: "RL1:1", gauge: 16 AWG, color: GNYE}
  - {id: W6, from: "TB5:1", to: "PP1:1", gauge: 16 AWG, color: BU}
  - {id: W7, from: "TB6:1", to: "PP2:1", gauge: 16 AWG, color: BN}
  - {id: W8, from: "J1:4", to: "TB1:1", gauge: 16 AWG, color: RD}
layout:
  root: B1
  segments: [[B1, TB5, 80], [B1, TB6, 65], [B1, TB1, 50], [B1, TB2, 60], [B1, TB3, 70], [B1, B2, 60], [B2, TB7, 20],
             [B2, TB4, 20], [B2, B3, 125], [B3, J1, 115], [B3, RL1, 150], [B3, B4, 175], [B4, PP1, 45], [B4, PP2, 40]]
""")

# A daisy chain of in-line fans, each labelled close to its body.
fan_chain = """
drawing: {title: FANS, number: T-31, rev: A}
connectors:
  PP1: {type: Powerpole, pn: PP-1, pincount: 1, label: VS+ BUS}
  PP2: {type: Powerpole, pn: PP-1, pincount: 1, label: VS- BUS}
  FAN1: {type: Fan lead, pn: F-2, pincount: 2, label: X1 FAN LEAD, double_crimp: [1, 2]}
  FAN2: {type: Fan lead, pn: F-2, pincount: 2, label: X2 FAN LEAD, double_crimp: [1, 2]}
  FAN3: {type: Fan lead, pn: F-2, pincount: 2, label: Y FAN LEAD, double_crimp: [1, 2]}
  FAN4: {type: Fan lead, pn: F-2, pincount: 2, label: Z FAN LEAD}
wires:
  - {id: W1, from: "PP1:1", to: "FAN1:1", gauge: 22 AWG, color: RD}
  - {id: W2, from: "PP2:1", to: "FAN1:2", gauge: 22 AWG, color: BU}
  - {id: W3, from: "FAN1:1", to: "FAN2:1", gauge: 22 AWG, color: RD}
  - {id: W4, from: "FAN1:2", to: "FAN2:2", gauge: 22 AWG, color: BU}
  - {id: W5, from: "FAN2:1", to: "FAN3:1", gauge: 22 AWG, color: RD}
  - {id: W6, from: "FAN2:2", to: "FAN3:2", gauge: 22 AWG, color: BU}
  - {id: W7, from: "FAN3:1", to: "FAN4:1", gauge: 22 AWG, color: RD}
  - {id: W8, from: "FAN3:2", to: "FAN4:2", gauge: 22 AWG, color: BU}
layout:
  root: PP1
  segments: [[PP1, B1, 175], [PP2, B1, 185], [B1, FAN1, 160], [FAN1, FAN2, 105], [FAN2, FAN3, 105], [FAN3, FAN4, 105]]
  labels:
    - {at: FAN2, text: "FAN2", distance: 30, item: LBL}
    - {at: FAN3, text: "FAN3", distance: 30, item: LBL}
    - {at: FAN4, text: "FAN4", distance: 30, item: LBL}
items:
  - {id: LBL, desc: Marker sleeve, qty: 3}
"""

# A short first leg with a label nearly as long as the leg, and a splice with labels on both sides.
mains_input = """
drawing: {title: MAINS INPUT, number: T-32, rev: A}
connectors:
  T1: {type: Transformer leads, pn: T-3, pincount: 3, label: T1 LEADS}
  QD1: {type: Quick disconnect, pn: QD-3, pincount: 3, label: INLET TABS}
  RL1: {type: Ring lug, pn: RL-1, pincount: 1, label: INLET PE STUD}
  PP1: {type: Powerpole, pn: PP-1, pincount: 1, label: LS BUS, SOURCE}
  PP2: {type: Powerpole, pn: PP-1, pincount: 1, label: N BUS, SOURCE, double_crimp: [1]}
  SP1: {type: splice, pn: SP-1}
wires:
  - {id: W1, from: "T1:1", to: "PP1:1", gauge: 16 AWG, color: BK}
  - {id: W2, from: "T1:2", to: "PP2:1", gauge: 16 AWG, color: BK}
  - {id: W3, from: "T1:3", to: SP1, gauge: 16 AWG, color: BK}
  - {id: W4, from: SP1, to: "QD1:1", gauge: 16 AWG, color: BK}
  - {id: W5, from: "QD1:2", to: "PP2:1", gauge: 16 AWG, color: WH}
  - {id: W6, from: "QD1:3", to: "RL1:1", gauge: 16 AWG, color: GNYE}
layout:
  root: T1
  segments: [[T1, B1, 15], [B1, B2, 155], [B1, B3, 65], [B1, RL1, 150], [B3, SP1, 125], [SP1, QD1, 60], [B2, PP1, 20], [B2, PP2, 25]]
  labels:
    - {at: T1, text: "T1 MAINS", distance: 5, item: LBL}
    - {at: SP1, text: "SP1 120V", distance: 20, item: LBL}
    - {at: QD1, text: "QD1 INLET", distance: 20, item: LBL}
items:
  - {id: LBL, desc: Marker sleeve, qty: 3}
"""

# One cable, labelled at both ends.
encoder_stub = """
drawing: {title: ENCODER STUB, number: T-33, rev: A}
connectors:
  P1: {type: CN2 plug, pn: CN2-6, pincount: 4, label: TO DRIVE CN2}
  J1: {type: XLR 4-pole, pn: AC4FDZ, pincount: 4, label: ENC RECEPTACLE}
cables:
  W1:
    desc: Encoder cable
    pn: ENC-4
    gauge: 26 AWG
    breakout: {P1: 0}
    conductors:
      - {color: RD, from: "P1:1", to: "J1:1"}
      - {color: BK, from: "P1:2", to: "J1:2"}
      - {color: BU, from: "P1:3", to: "J1:3", twist: T1}
      - {color: WH, from: "P1:4", to: "J1:4", twist: T1}
layout:
  root: P1
  segments: [[P1, J1, 240]]
  labels:
    - {at: P1, text: "X1 ENC", distance: 50, item: LBL}
    - {at: J1, text: "X1 ENC", distance: 50, item: LBL}
items:
  - {id: LBL, desc: Marker sleeve, qty: 2}
"""

# Sensors on lengths not decided yet, labelled near their ends, beside two splices.
rail_sensors = """
drawing: {title: RAIL SENSORS, number: T-34, rev: A}
connectors:
  J1: {type: Bulkhead, pn: BH-6, pincount: 6, label: SNS BULKHEAD}
  D1: {type: Sensor, pn: S-3, pincount: 3, label: X1 NL SENSOR}
  D2: {type: Sensor, pn: S-3, pincount: 3, label: X1 PL SENSOR}
  D3: {type: Sensor, pn: S-3, pincount: 3, label: X1 HOME SENSOR}
  SP1: {type: splice, pn: SP-1}
  SP2: {type: splice, pn: SP-1}
wires:
  - {id: W1, from: "J1:1", to: SP1, gauge: 22 AWG, color: RD}
  - {id: W2, from: SP1, to: "D1:1", gauge: 22 AWG, color: RD}
  - {id: W3, from: SP1, to: "D2:1", gauge: 22 AWG, color: RD}
  - {id: W4, from: SP1, to: "D3:1", gauge: 22 AWG, color: RD}
  - {id: W5, from: "J1:2", to: SP2, gauge: 22 AWG, color: BU}
  - {id: W6, from: SP2, to: "D1:2", gauge: 22 AWG, color: BU}
  - {id: W7, from: SP2, to: "D2:2", gauge: 22 AWG, color: BU}
  - {id: W8, from: SP2, to: "D3:2", gauge: 22 AWG, color: BU}
  - {id: W9, from: "J1:3", to: "D1:3", gauge: 22 AWG, color: BK}
  - {id: W10, from: "J1:4", to: "D2:3", gauge: 22 AWG, color: WH}
  - {id: W11, from: "J1:5", to: "D3:3", gauge: 22 AWG, color: GY}
layout:
  root: J1
  segments: [[J1, B1, TBD], [B1, SP1, TBD], [B1, SP2, TBD], [B1, D1, TBD], [B1, D2, TBD], [B1, D3, TBD]]
  labels:
    - {at: D1, text: "X1 NL", distance: 50, item: LBL}
    - {at: D2, text: "X1 PL", distance: 50, item: LBL}
items:
  - {id: LBL, desc: Marker sleeve, qty: 2}
"""

gantry_shaped = {"power": power_harness, "fan chain": fan_chain, "mains input": mains_input, "encoder stub": encoder_stub,
                 "rail sensors": rail_sensors}


class NothingDrawnOverAnythingTest(unittest.TestCase):
    def test_harnesses_shaped_like_the_gantry_run_are_drawn_clean(self) -> None:
        for name, source in gantry_shaped.items():
            with self.subTest(name):
                analysis = analysed(source)
                self.assertEqual(sheet_collisions(analysis.sheet_layout), [])
                self.assertNotIn("ERROR", analysis.findings.report(), name)

    def test_every_example_is_drawn_clean(self) -> None:
        for name in example_names:
            with self.subTest(name):
                analysis = analysed((examples_directory / name / f"{name}.yaml").read_text())
                self.assertEqual(sheet_collisions(analysis.sheet_layout), [])

    def test_a_ten_leaf_harness_fits_without_dropping_anything(self) -> None:
        layout = analysed(power_harness).sheet_layout
        captions = {name for name, _ in layout.texts if name.endswith(" caption")}
        self.assertEqual(len(captions), 11)


class CollisionCheckTest(unittest.TestCase):
    def test_text_over_text_is_named(self) -> None:
        layout = SheetLayout({})
        layout.texts += [("label A", (0, 0, 50, 18)), ("A balloons", (40, 5, 62, 27))]
        self.assertEqual(sheet_collisions(layout), ["A balloons over label A"])

    def test_a_balloon_on_a_bundle_and_text_on_a_dimension_line(self) -> None:
        layout = SheetLayout({})
        layout.bundles.append(("bundle B1–J1", [(0, 100), (300, 100)], 3, set()))
        layout.texts.append(("J1 balloons", (100, 90, 122, 112)))
        layout.dimension_lines.append(("dimension B1–J1", (0, 200, 300, 208)))
        layout.texts.append(("connector J2 caption", (50, 195, 120, 225)))
        self.assertEqual(sheet_collisions(layout), ["J1 balloons over bundle B1–J1", "connector J2 caption over dimension B1–J1"])

    def test_what_belongs_together_may_touch(self) -> None:
        layout = SheetLayout({})
        layout.dimension_lines.append(("dimension B1–J1", (0, 200, 300, 208)))
        layout.texts.append(("dimension B1–J1", (130, 197, 170, 211)))
        layout.bundles.append(("bundle B1–J1", [(0, 100), (300, 100)], 3, {"connector J1"}))
        layout.bodies.append(("connector J1", (274, 80, 364, 120)))
        self.assertEqual(sheet_collisions(layout), [])

    def test_a_drawing_that_cannot_be_drawn_clean_is_an_error(self) -> None:
        source = encoder_stub.replace('{at: J1, text: "X1 ENC", distance: 50', '{at: P1, text: "X1 ENC", distance: 50')
        checks = analysed(source).findings.report()
        self.assertRegex(checks, r"ERROR +sheet 1 draws label X1 ENC.* over ")



class OverallDimensionTest(unittest.TestCase):
    def test_a_leaf_one_segment_from_the_root_has_no_second_dimension(self) -> None:
        layout = analysed(power_harness).sheet_layout
        overall = sorted(name.removeprefix("overall dimension B1–") for name, _ in layout.dimension_lines if name.startswith("overall"))
        self.assertEqual(overall, ["J1", "PP1", "PP2", "RL1", "TB4", "TB7"], "TB1, TB2, TB3, TB5 and TB6 have their segment's dimension")


if __name__ == "__main__":
    unittest.main()
