"""A mistake in the harness source comes back as a finding, never as a traceback."""
import tempfile
import unittest
from pathlib import Path

from tests.generator import run_generator_on_text
from tests.test_output_integrity import two_wire_harness


class BadInputTest(unittest.TestCase):
    # Run both ways a user runs the generator, and return the checks report of the full run.
    def findings_for(self, source_text: str) -> str:
        """The checks report for a source, after making sure neither run raised."""
        reports = []
        for options in (("--check-only",), ("--no-wireviz",)):
            directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
            process = run_generator_on_text(source_text, directory, *options)
            self.assertNotIn("Traceback", process.stderr, f"{options}: {process.stderr}")
            self.assertEqual(process.returncode, 1, f"{options}: {process.stdout}")
            reports.append((directory / "harness.checks.txt").read_text())
        self.assertEqual(reports[0], reports[1])
        return reports[1]

    def test_a_gauge_without_a_unit(self) -> None:
        findings = self.findings_for(two_wire_harness.replace("gauge: 24 AWG, color: BK", "gauge: 24, color: BK"))
        self.assertRegex(findings, r"ERROR +W1: gauge '24' has no unit")

    def test_a_wire_without_an_end(self) -> None:
        findings = self.findings_for(two_wire_harness.replace('from: "P1:1", ', ""))
        self.assertRegex(findings, r"ERROR +W1: missing 'from'")

    def test_a_covering_on_a_segment_not_in_the_layout(self) -> None:
        source = two_wire_harness + "  coverings: [{item: SLV, segments: [P1-X9]}]\nitems: [{id: SLV, desc: Sleeving, qty: AR}]\n"
        self.assertRegex(self.findings_for(source), r"ERROR +covering SLV: segment P1-X9 is not in layout.segments")

    def test_empty_sections(self) -> None:
        source = two_wire_harness.replace("drawing: {title: TWO WIRE, number: T-1, rev: A}", "drawing:\ncables:\nitems:")
        source = source.replace("signal: GND, gauge: 24 AWG, color: BK", "signal: GND, gauge: 24, color: BK")
        self.assertIn("has no unit", self.findings_for(source))

    def test_a_round_to_of_zero(self) -> None:
        findings = self.findings_for(two_wire_harness.replace("rev: A}", "rev: A, round_to: 0}"))
        self.assertRegex(findings, r"ERROR +drawing.round_to must be a number greater than 0")

    def test_lengths_that_are_not_numbers(self) -> None:
        source = two_wire_harness.replace("rev: A}", "rev: A, extra_per_wire: lots}").replace("[[P1, J1, 500]]", "[[P1, J1, long]]")
        source = source.replace("color: RD}", "color: RD, length: short}").replace("P1: {type", "P1: {wire_allowance: some, type")
        findings = self.findings_for(source)
        self.assertRegex(findings, r"ERROR +drawing.extra_per_wire must be a number")
        self.assertRegex(findings, r"ERROR +layout segment P1-J1: length 'long' must be a number or TBD")
        self.assertRegex(findings, r"ERROR +W2: length 'short' must be a number")
        self.assertRegex(findings, r"ERROR +P1: wire_allowance must be a number")


if __name__ == "__main__":
    unittest.main()
