"""Connectors not yet chosen draw as generic parts, and a stated cavity layout draws as a pinout."""
import re
import tempfile
import unittest
from pathlib import Path

from tests.generator import run_generator_on_text
from tests.test_output_integrity import generate, two_wire_harness

from harness.source import cavity_positions  # noqa: E402  (tests.generator puts scripts/ on the path)

generic_harness = """
drawing: {title: GENERIC, number: T-5, rev: A}
connectors:
  P1: {pincount: 4, shape: circular, gender: male}
  J1: {type: KK 254, pincount: 4, pn: 22-01-3047, manufacturer: Molex, gender: female,
       face: {grid: [1, 4], view: mating face}}
wires:
  - {id: W1, from: "P1:1", to: "J1:1", gauge: 24 AWG, color: BK}
  - {id: W2, from: "P1:2", to: "J1:2", gauge: 24 AWG, color: RD}
layout:
  root: P1
  segments: [[P1, J1, 500]]
"""


class GenericConnectorTest(unittest.TestCase):
    def test_a_connector_without_a_part_number_is_reported_as_generic(self) -> None:
        self.assertIn("WARN   P1: no part number; drawn as a generic connector", generate(self, generic_harness).read("checks.txt"))

    def test_the_bom_names_it_as_a_generic_part(self) -> None:
        row = generate(self, generic_harness).bom_rows()[0]
        self.assertEqual((row["pn"], row["description"]), ("TBD", "Generic 4-position connector, circular, male"))

    def test_sheet_one_draws_it_as_generic_in_its_shape_and_gender(self) -> None:
        sheet = generate(self, generic_harness).sheets()[0]
        self.assertEqual(len(re.findall(r'class="connector-body generic circular"', sheet)), 1)
        self.assertEqual(len(re.findall(r'class="connector-body rectangular"', sheet)), 1)
        self.assertEqual(sheet.count('class="mating-male"'), 1)
        self.assertEqual(sheet.count('class="mating-female"'), 1)
        self.assertIn(">GENERIC 4-PIN<", sheet)

    def test_a_chosen_connector_is_not_called_generic(self) -> None:
        self.assertNotIn("generic", generate(self, two_wire_harness.replace("pincount: 2,", "pincount: 2, pn: X1,")).sheets()[0])


class CavityLayoutTest(unittest.TestCase):
    def test_a_grid_numbers_its_cavities_row_by_row(self) -> None:
        positions = cavity_positions({"pincount": 6, "face": {"grid": [2, 3]}})
        self.assertEqual(positions, {"1": (0, 0), "2": (1, 0), "3": (2, 0), "4": (0, 1), "5": (1, 1), "6": (2, 1)})

    def test_a_grid_can_number_column_by_column(self) -> None:
        positions = cavity_positions({"pincount": 4, "face": {"grid": [2, 2], "numbering": "columns"}})
        self.assertEqual(positions, {"1": (0, 0), "2": (0, 1), "3": (1, 0), "4": (1, 1)})

    def test_a_ring_starts_at_the_top_and_runs_clockwise(self) -> None:
        positions = cavity_positions({"pincount": 4, "face": {"ring": True}})
        self.assertEqual({pin: (round(x, 6), round(y, 6)) for pin, (x, y) in positions.items()},
                         {"1": (0, -1), "2": (1, 0), "3": (0, 1), "4": (-1, 0)})

    def test_explicit_cavities_are_used_as_given(self) -> None:
        positions = cavity_positions({"pins": ["A", "B"], "face": {"cavities": {"A": [0, 0], "B": [3.5, 1]}}})
        self.assertEqual(positions, {"A": (0, 0), "B": (3.5, 1)})

    def test_no_stated_layout_means_no_positions(self) -> None:
        self.assertEqual(cavity_positions({"pincount": 4}), {})


class PinoutDiagramTest(unittest.TestCase):
    def test_a_connector_with_a_stated_face_gets_a_pinout_diagram(self) -> None:
        tables = generate(self, generic_harness).sheets()[1]
        diagram = re.search(r'<g class="pinout" data-connector="J1">(.*?)</g>', tables, re.S)
        self.assertIsNotNone(diagram)
        self.assertEqual(diagram.group(1).count("<circle"), 4)
        self.assertIn('fill="#1a1a1a"', diagram.group(1), "pin 1 carries the BK wire")
        self.assertIn(">J1 PINOUT, MATING FACE<", tables)

    def test_a_connector_without_one_gets_no_diagram(self) -> None:
        self.assertNotIn('data-connector="P1"', generate(self, generic_harness).sheets()[1])


class ConnectorValueTest(unittest.TestCase):
    def findings_for(self, replacement: tuple[str, str]) -> str:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        process = run_generator_on_text(generic_harness.replace(*replacement), directory, "--check-only")
        self.assertNotIn("Traceback", process.stderr, process.stderr)
        return (directory / "harness.checks.txt").read_text()

    def test_shape_and_gender_take_known_words(self) -> None:
        findings = self.findings_for(("shape: circular, gender: male", "shape: oval, gender: both"))
        self.assertIn("ERROR  P1: shape 'oval' is not rectangular or circular", findings)
        self.assertIn("ERROR  P1: gender 'both' is not male or female", findings)

    def test_a_grid_must_hold_every_pin(self) -> None:
        self.assertIn("ERROR  J1: face grid 1×3 has 3 cavities for 4 pins",
                      self.findings_for(("grid: [1, 4]", "grid: [1, 3]")))

    def test_explicit_cavities_must_place_every_pin(self) -> None:
        self.assertIn("ERROR  J1: face cavities do not place pins 3, 4",
                      self.findings_for(("grid: [1, 4]", "cavities: {1: [0, 0], 2: [1, 0]}")))

    def test_a_face_names_one_layout_and_a_known_view(self) -> None:
        findings = self.findings_for(("grid: [1, 4], view: mating face", "grid: [1, 4], ring: true, view: side"))
        self.assertIn("ERROR  J1: face must give exactly one of grid, ring or cavities", findings)
        self.assertIn("ERROR  J1: face view 'side' is not mating face or rear", findings)


if __name__ == "__main__":
    unittest.main()
