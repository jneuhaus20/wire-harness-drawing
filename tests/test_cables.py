"""A multi-conductor cable is one item: one designator, conductors named within it, and cut lengths for the cable."""
import csv
import tempfile
import unittest
from pathlib import Path

from tests.generator import run_generator_on_text
from tests.test_output_integrity import GeneratedPackage, svg_texts

from harness.explorer_model import harness_model  # noqa: E402  (tests.generator puts scripts/ on the path)
from harness.package import analyse
from harness.source import load_source

# W5 runs from P1 through B1 to B2, where it splits: two conductors to J2 (150 on), two to J3 (250 on).
split_cable_harness = """
drawing: {title: SPLIT CABLE, number: T-10, rev: A}
connectors:
  P1: {type: KK 254, pn: A-1, pincount: 5, pinlabels: [PWR, A+, A-, B+, B-]}
  J1: {type: KK 254, pn: A-2, pincount: 1, pinlabels: [PWR]}
  J2: {type: KK 254, pn: A-3, pincount: 2, pinlabels: [A+, A-]}
  J3: {type: KK 254, pn: A-4, pincount: 2, pinlabels: [B+, B-]}
cables:
  W5:
    desc: 4-conductor shielded, 24 AWG
    pn: C-4
    gauge: 24 AWG
    color: BK
    conductors:
      - {color: RD, from: "P1:2", to: "J2:1", signal: A+}
      - {color: BK, from: "P1:3", to: "J2:2", signal: A-}
      - {color: WH, from: "P1:4", to: "J3:1", signal: B+}
      - {color: GN, from: "P1:5", to: "J3:2", signal: B-}
wires:
  - {id: W1, from: "P1:1", to: "J1:1", signal: PWR, gauge: 22 AWG, color: RD}
layout:
  root: P1
  segments: [[P1, B1, 300], [B1, J1, 200], [B1, B2, 100], [B2, J2, 150], [B2, J3, 250]]
"""


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
