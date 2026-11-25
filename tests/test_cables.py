"""A multi-conductor cable is one item: one designator, conductors named within it, and cut lengths for the cable."""
import csv
import tempfile
import unittest
from pathlib import Path

from tests.generator import run_generator_on_text, example_text
from tests.test_bad_input import BadInputTest
from tests.test_output_integrity import GeneratedPackage, svg_texts

from harness.explorer_model import harness_model  # noqa: E402  (tests.generator puts scripts/ on the path)
from harness.package import analyse
from harness.source import load_source

# W5 runs from P1 through B1 to B2, where it splits: two conductors to J2 (150 on), two to J3 (250 on).
split_cable_harness = example_text("split-cable")


class CableCutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = GeneratedPackage(split_cable_harness)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.package.close()

    def rows(self, suffix: str) -> list[dict[str, str]]:
        return list(csv.DictReader(self.package.read(suffix).splitlines()))

    def test_the_source_is_clean(self) -> None:
        self.assertEqual(self.package.read("checks.txt"), "OK     no findings\n")

    def test_the_cable_is_cut_once_with_its_jacket_and_leads(self) -> None:
        [cable] = self.rows("cables.csv")
        self.assertEqual({key: cable[key] for key in ("cable", "cut_length", "jacket_length", "strip_a", "end_a", "strip_b", "end_b")},
                         {"cable": "W5", "cut_length": "650", "jacket_length": "360", "strip_a": "40", "end_a": "P1",
                          "strip_b": "250", "end_b": "B2"})

    def test_each_conductor_has_a_lead_at_each_end_and_no_cut_length_of_its_own(self) -> None:
        conductors = {row["wire"]: row for row in self.rows("wirelist.csv") if row["cable"] == "W5"}
        self.assertEqual(sorted(conductors), ["W5-BK", "W5-GN", "W5-RD", "W5-WH"])
        self.assertEqual({wire: (row["lead_a"], row["lead_b"], row["cut_length"]) for wire, row in conductors.items()},
                         {"W5-RD": ("40", "150", ""), "W5-BK": ("40", "150", ""), "W5-WH": ("40", "250", ""), "W5-GN": ("40", "250", "")})

    def test_the_bom_buys_the_cable_by_its_cut_length(self) -> None:
        line = next(row for row in csv.DictReader(self.package.read("bom.csv").splitlines()) if row["pn"] == "C-4")
        self.assertEqual((line["qty"], line["refs"]), ("0.65", "W5"))

    def test_the_table_sheet_lists_the_cable_once(self) -> None:
        texts = svg_texts(self.package.sheets()[1])
        self.assertIn("CABLE LIST", texts)
        self.assertEqual(texts.count("W5-RD"), 3, "in the cable list and the tables of P1 and J2, not in the wire list")


class CableModelTest(unittest.TestCase):
    def test_the_explorer_gets_the_jacket_run_and_its_ends(self) -> None:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (directory / "harness.yaml").write_text(split_cable_harness)
        [cable] = harness_model(analyse(load_source(directory / "harness.yaml")))["cables"]
        self.assertEqual(cable["run"], ["P1", "B1", "B2"])
        self.assertEqual(cable["breakouts"], {"P1": 40, "B2": 0})
        self.assertEqual(cable["cut_length"], "650")
        self.assertEqual(cable["ends"], [{"node": "P1", "strip_back": "40", "leads": {"W5-RD": "40", "W5-BK": "40", "W5-WH": "40", "W5-GN": "40"}},
                                         {"node": "B2", "strip_back": "250", "leads": {"W5-RD": "150", "W5-BK": "150", "W5-WH": "250", "W5-GN": "250"}}])


class CableSourceTest(unittest.TestCase):
    def findings_for(self, source: str) -> str:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        process = run_generator_on_text(source, directory, "--check-only")
        self.assertNotIn("Traceback", process.stderr, process.stderr)
        return (directory / "harness.checks.txt").read_text()

    def test_a_conductor_is_named_by_colour_or_number(self) -> None:
        source = split_cable_harness.replace('{color: RD, from: "P1:2"', '{from: "P1:2"')
        self.assertIn("ERROR  cable W5: conductor 1 needs a color or a number", self.findings_for(source))

    def test_a_drain_wire_is_a_conductor_named_for_the_shield(self) -> None:
        source = split_cable_harness.replace('      - {color: GN, from: "P1:5", to: "J3:2", signal: B-}\n',
                                              '      - {color: GN, from: "P1:5", to: "J3:2", signal: B-}\n      - {drain: true, from: "P1:1", to: "J3:2"}\n')
        package = GeneratedPackage(source)
        self.addCleanup(package.close)
        rows = {row["wire"]: row for row in csv.DictReader(package.read("wirelist.csv").splitlines())}
        self.assertEqual((rows["W5-SH"]["color"], rows["W5-SH"]["cable"]), ("SR", "W5"))

    def test_a_conductor_number_names_it(self) -> None:
        source = split_cable_harness.replace('{color: RD, from: "P1:2"', '{number: 1, from: "P1:2"')
        self.assertNotIn("ERROR", self.findings_for(source))

    def test_the_old_cable_key_on_a_wire_is_refused(self) -> None:
        source = split_cable_harness.replace("color: RD}\n", "color: RD, cable: W5}\n")
        self.assertIn("ERROR  W1: list a cable's conductors under cables.W5.conductors; a wire's cable key is not read",
                      self.findings_for(source))

    def test_a_breakout_length_can_be_set(self) -> None:
        source = split_cable_harness.replace("    color: BK\n", "    color: BK\n    breakout: 60\n")
        package = GeneratedPackage(source)
        self.addCleanup(package.close)
        [cable] = list(csv.DictReader(package.read("cables.csv").splitlines()))
        self.assertEqual((cable["jacket_length"], cable["strip_a"], cable["cut_length"]), ("340", "60", "650"))


if __name__ == "__main__":
    unittest.main()


# The encoder stub from the gantry run: one cable whose own moulded plug P1 is at one end, its
# conductors soldered into J1 at the other, its signal pair twisted inside it.
encoder_stub = """
drawing: {title: ENCODER STUB, number: T-20, rev: A}
connectors:
  P1: {type: CN2 plug, pn: CN2-6, pins: [1, 2, 5, 6]}
  J1: {type: XLR 4-pole, pn: AC4FDZ, pincount: 4}
cables:
  W1:
    desc: Encoder cable
    pn: ENC-4
    gauge: 26 AWG
    breakout: {P1: 0}
    conductors:
      - {color: RD, from: "P1:1", to: "J1:1", signal: +5V}
      - {color: BK, from: "P1:2", to: "J1:2", signal: GND}
      - {color: BU, from: "P1:5", to: "J1:3", signal: T+, twist: T1}
      - {color: WH, from: "P1:6", to: "J1:4", signal: T-, twist: T1}
layout:
  root: P1
  segments: [[P1, J1, 240]]
"""


class CableOnlyHarnessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = GeneratedPackage(encoder_stub)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.package.close()

    def test_the_source_is_clean(self) -> None:
        self.assertEqual(self.package.read("checks.txt"), "OK     no findings\n")

    def test_no_empty_wire_list_is_printed(self) -> None:
        texts = svg_texts(self.package.sheets()[1])
        self.assertNotIn("WIRE LIST (FROM–TO)", texts)
        self.assertIn("CABLE LIST", texts)
        self.assertIn("BOM / CABLE LIST / CONNECTORS", texts, "the sheet is titled for what it holds")

    def test_no_take_up_note_when_no_cut_wire_is_twisted(self) -> None:
        notes = " ".join(svg_texts(self.package.sheets()[0]))
        self.assertNotIn("TAKE-UP", notes)
        self.assertIn("TWIST INDICATED WIRES PER IPC/WHMA-A-620", notes)

    def test_the_cable_list_shows_the_twist(self) -> None:
        sheet = self.package.sheets()[1]
        cable_list = sheet[sheet.index(">CABLE LIST<"):]
        self.assertIn(">TWIST<", cable_list)
        self.assertEqual(svg_texts(cable_list).count("T1"), 2)

    def test_a_factory_terminated_end_has_no_breakout(self) -> None:
        [cable] = list(csv.DictReader(self.package.read("cables.csv").splitlines()))
        self.assertEqual((cable["end_a"], cable["strip_a"], cable["end_b"], cable["strip_b"], cable["jacket_length"]),
                         ("P1", "0", "J1", "40", "200"))


class CableBreakoutSourceTest(unittest.TestCase):
    findings_for = CableSourceTest.findings_for

    def test_a_breakout_must_be_a_length(self) -> None:
        findings = self.findings_for(encoder_stub.replace("breakout: {P1: 0}", "breakout: {P1: none}"))
        self.assertIn("ERROR  cable W1: breakout at P1 must be a number of 0 or more, not 'none'", findings)
        findings = self.findings_for(encoder_stub.replace("breakout: {P1: 0}", "breakout: -5"))
        self.assertIn("ERROR  cable W1: breakout must be a number of 0 or more, not '-5'", findings)

    def test_a_breakout_at_a_node_the_jacket_does_not_end_at(self) -> None:
        findings = self.findings_for(encoder_stub.replace("breakout: {P1: 0}", "breakout: {P9: 0}"))
        self.assertIn("ERROR  cable W1: breakout names P9, which is not an end of its jacket (P1, J1)", findings)


# Version 1.0 took a cable's conductor count and a cable key on each wire. That form is refused
# with findings that say how to write it now, never a traceback.
version_one_cable = """
drawing: {title: OLD FORM, number: T-21, rev: A}
connectors:
  P1: {type: KK 254, pn: A-1, pincount: 2}
  J1: {type: KK 254, pn: A-2, pincount: 2}
cables:
  C1: {desc: 2-conductor, pn: C-2, conductors: 2}
wires:
  - {id: W1, from: "P1:1", to: "J1:1", gauge: 24 AWG, color: BK, cable: C1}
  - {id: W2, from: "P1:2", to: "J1:2", gauge: 24 AWG, color: RD, cable: C1}
layout:
  root: P1
  segments: [[P1, J1, 300]]
"""


class VersionOneCableTest(unittest.TestCase):
    findings_for = BadInputTest.findings_for

    def test_a_conductor_count_is_an_error_not_a_crash(self) -> None:
        findings = self.findings_for(version_one_cable)
        self.assertIn("ERROR  cable C1: conductors must be a list of conductors, each with from and to, not 2", findings)
        self.assertIn("ERROR  W1: list a cable's conductors under cables.C1.conductors; a wire's cable key is not read", findings)
        self.assertNotIn("has no conductors", findings, "the error already says so")

    def test_the_package_is_marked_not_for_release(self) -> None:
        package = GeneratedPackage(version_one_cable)
        self.addCleanup(package.close)
        self.assertEqual(package.process.returncode, 1)
        self.assertTrue(all("NOT FOR RELEASE" in sheet for sheet in package.sheets()))

    def test_a_conductor_that_is_not_a_mapping(self) -> None:
        findings = self.findings_for(version_one_cable.replace("conductors: 2", 'conductors: ["P1:1 to J1:1"]'))
        self.assertIn("ERROR  cable C1: conductor 1 must be a mapping with from and to, not 'P1:1 to J1:1'", findings)
