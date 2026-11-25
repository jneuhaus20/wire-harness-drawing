"""A source with lengths still unknown, or known only as a minimum, still yields a useful package."""
import tempfile
import unittest
from pathlib import Path

from tests.generator import run_generator_on_text, example_text
from tests.test_output_integrity import GeneratedPackage, svg_texts

minimum_length_harness = example_text("unknowns")


class MinimumLengthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = GeneratedPackage(minimum_length_harness)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.package.close()

    def test_cut_lengths_through_a_minimum_are_minimums(self) -> None:
        rows = {row.split(",")[0]: row.split(",")[8] for row in self.package.read("wirelist.csv").splitlines()[1:]}
        self.assertEqual(rows, {"W1": "≥500", "W2": "TBD"})

    def test_the_bom_buys_at_least_the_minimum(self) -> None:
        quantities = {row["refs"]: row["qty"] for row in self.package.bom_rows() if "AWG" in row["description"]}
        self.assertEqual(quantities, {"W1": "≥0.5", "W2": "TBD"})
        self.assertIn("AR (≥0.50)", svg_texts(self.package.sheets()[1]))

    def test_the_drawing_dimensions_a_minimum_as_one(self) -> None:
        drawing_text = svg_texts(self.package.sheets()[0])
        self.assertIn("≥200", drawing_text)
        self.assertIn("≥500 REF  (P1–J1)", drawing_text)
        self.assertIn("TBD REF  (P1–J2)", drawing_text)

    def test_every_unknown_length_is_drawn_with_a_break(self) -> None:
        self.assertEqual(self.package.sheets()[0].count('class="length-break"'), 2)

    def test_the_notes_say_what_a_minimum_means(self) -> None:
        notes = " ".join(svg_texts(self.package.sheets()[0]))
        self.assertIn("LENGTHS MARKED ≥ ARE MINIMUMS", notes)

    def test_the_report_lists_the_minimum(self) -> None:
        self.assertIn("B1-J1 (≥200)", self.package.read("checks.txt"))


class MinimumValueTest(unittest.TestCase):
    def findings_for(self, segment_length: str) -> str:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        source = minimum_length_harness.replace("{min: 200}", segment_length)
        process = run_generator_on_text(source, directory, "--check-only")
        self.assertNotIn("Traceback", process.stderr, process.stderr)
        return (directory / "harness.checks.txt").read_text()

    def test_a_minimum_must_be_a_number_of_zero_or_more(self) -> None:
        self.assertIn("ERROR  layout segment B1-J1: minimum length 'short' must be a number of 0 or more",
                      self.findings_for("{min: short}"))
        self.assertIn("ERROR  layout segment B1-J1: minimum length '-5' must be a number of 0 or more",
                      self.findings_for("{min: -5}"))

    def test_a_length_mapping_takes_only_min(self) -> None:
        self.assertIn("ERROR  layout segment B1-J1: length {'max': 5} must be a number, TBD or {min: N}",
                      self.findings_for("{max: 5}"))


if __name__ == "__main__":
    unittest.main()
