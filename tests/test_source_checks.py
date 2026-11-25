"""Mistakes the generator used to accept silently are now reported."""
import tempfile
import unittest
from pathlib import Path

from tests.generator import run_generator_on_text
from tests.test_output_integrity import two_wire_harness

labelled_harness = two_wire_harness.replace("pinlabels: [GND, VCC]}", "pinlabels: [GND, VCC], pn: 22-01-3027}") + """  coverings: [{item: SLV, segments: [P1-J1]}]
  labels:
    - {at: P1, text: P1, distance: 50, item: LBL}
    - {at: J1, text: J1, distance: 50, item: LBL}
items:
  - {id: SLV, desc: Sleeving, qty: AR, unit: m}
  - {id: LBL, desc: Marker sleeve, qty: 2}
"""


class SourceChecksTest(unittest.TestCase):
    def findings_for(self, source_text: str) -> str:
        """The checks report for a source; the run must not raise."""
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        process = run_generator_on_text(source_text, directory, "--no-wireviz")
        self.assertNotIn("Traceback", process.stderr, process.stderr)
        return (directory / "harness.checks.txt").read_text()

    def test_the_labelled_harness_is_clean(self) -> None:
        self.assertEqual(self.findings_for(labelled_harness), "OK     no findings\n")

    # A contact's AWG range is the maker's rating; a wire outside it may still crimp well, so the
    # shop decides. It is reported for that decision and does not stop release.
    def test_a_gauge_outside_the_contact_range_is_a_warning(self) -> None:
        source = labelled_harness.replace("J1: {type: KK 254, pincount: 2,", "J1: {type: KK 254, awg: [24, 30], pincount: 2,")
        source = source.replace("gauge: 24 AWG, color: RD}", "gauge: 22 AWG, color: RD}")
        findings = self.findings_for(source)
        self.assertIn("WARN   J1: W2 (22 AWG) is outside its contact range 24-30 AWG; confirm the crimp before release", findings)
        self.assertNotIn("ERROR", findings)

    def test_wires_outside_a_contact_range_are_reported_once_per_connector(self) -> None:
        source = labelled_harness.replace("J1: {type: KK 254, pincount: 2,", "J1: {type: KK 254, awg: [26, 30], pincount: 2,")
        source = source.replace("gauge: 24 AWG, color: RD}", "gauge: 22 AWG, color: RD}")
        self.assertIn("WARN   J1: W1 (24 AWG), W2 (22 AWG) are outside its contact range 26-30 AWG; confirm the crimp before release",
                      self.findings_for(source))

    def test_a_gauge_inside_the_contact_range_is_not_reported(self) -> None:
        source = labelled_harness.replace("J1: {type: KK 254, pincount: 2,", "J1: {type: KK 254, awg: [24, 30], pincount: 2,")
        self.assertEqual(self.findings_for(source), "OK     no findings\n")

    def test_a_covering_item_that_is_not_listed(self) -> None:
        findings = self.findings_for(labelled_harness.replace("{item: SLV,", "{item: SLV9,"))
        self.assertRegex(findings, r"ERROR +covering SLV9: item SLV9 is not in items")

    def test_a_label_at_an_unknown_node(self) -> None:
        findings = self.findings_for(labelled_harness.replace("{at: J1, text: J1,", "{at: J7, text: J1,"))
        self.assertRegex(findings, r"ERROR +label J1: at J7, which is not a layout node")

    def test_a_label_item_that_is_not_listed(self) -> None:
        findings = self.findings_for(labelled_harness.replace("distance: 50, item: LBL}\n    - {at: J1", "distance: 50, item: TAG}\n    - {at: J1"))
        self.assertRegex(findings, r"ERROR +label P1: item TAG is not in items")

    def test_a_label_farther_than_the_standard_allows(self) -> None:
        source = labelled_harness.replace("text: J1, distance: 50", "text: J1, distance: 320")
        self.assertRegex(self.findings_for(source), r"WARN +label J1: 320 mm from J1 exceeds the 300 mm limit")

    def test_a_label_beyond_its_segment(self) -> None:
        source = labelled_harness.replace("[[P1, J1, 500]]", "[[P1, J1, 200]]").replace("text: J1, distance: 50", "text: J1, distance: 250")
        self.assertRegex(self.findings_for(source), r"ERROR +label J1: 250 mm from J1 is beyond the 200 mm segment J1-P1")

    def test_a_label_count_that_differs_from_its_item_quantity(self) -> None:
        source = labelled_harness.replace("desc: Marker sleeve, qty: 2", "desc: Marker sleeve, qty: 3")
        self.assertRegex(self.findings_for(source), r"ERROR +item LBL: qty 3 but 2 labels use it")

    def test_a_negative_segment_length(self) -> None:
        findings = self.findings_for(two_wire_harness.replace("[[P1, J1, 500]]", "[[P1, J1, -500]]"))
        self.assertRegex(findings, r"ERROR +layout segment P1-J1: length -500 is negative")

    def test_a_tolerance_table_without_a_catch_all_row(self) -> None:
        source = two_wire_harness.replace("rev: A}", "rev: A, tolerance: [{upto: 300, tol: 5}]}")
        self.assertRegex(self.findings_for(source),
                         r"ERROR +drawing.tolerance has no row with upto: null; lengths over 300 have no tolerance")

    def test_a_wire_end_without_a_pin_on_a_multi_pin_connector(self) -> None:
        findings = self.findings_for(two_wire_harness.replace('to: "J1:2"', 'to: "J1"'))
        self.assertRegex(findings, r"ERROR +W2: to 'J1' names no pin, and J1 has 2")

    def test_a_single_pin_end_needs_no_pin(self) -> None:
        source = two_wire_harness.replace("J1: {type: KK 254, pincount: 2, pinlabels: [GND, VCC]}",
                                          "J1: {type: KK 254, pincount: 2, pinlabels: [GND, VCC]}\n  E1: {type: Ring lug, pincount: 1}")
        source = source.replace('to: "J1:2"', 'to: "E1"').replace("segments: [[P1, J1, 500]]", "segments: [[P1, B1, 400], [B1, J1, 100], [B1, E1, 100]]")
        self.assertNotIn("names no pin", self.findings_for(source))

    def test_a_gauge_that_cannot_be_checked_against_the_contact_range(self) -> None:
        source = two_wire_harness.replace("J1: {type: KK 254,", "J1: {awg: [22, 30], type: KK 254,")
        source = source.replace("gauge: 24 AWG, color: BK", "gauge: 0.25 mm², color: BK")
        self.assertRegex(self.findings_for(source),
                         r"WARN +W1: gauge '0.25 mm²' is not in AWG, so it was not checked against J1's 22-30 AWG range")

    def test_a_label_distance_that_is_not_a_number(self) -> None:
        findings = self.findings_for(labelled_harness.replace("text: J1, distance: 50", "text: J1, distance: near"))
        self.assertRegex(findings, r"ERROR +label J1: distance 'near' must be a number")

    def test_a_label_without_a_place(self) -> None:
        findings = self.findings_for(labelled_harness.replace("{at: J1, text: J1,", "{text: J1,"))
        self.assertRegex(findings, r"ERROR +label J1: missing 'at'")


if __name__ == "__main__":
    unittest.main()
