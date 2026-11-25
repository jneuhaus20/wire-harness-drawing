"""A colour is read however a person would write it, and kept as its IEC 60757 code."""
import csv
import tempfile
import unittest
from pathlib import Path

from tests.generator import example_text, run_generator_on_text

from harness.source import iec_color_code  # noqa: E402  (tests.generator puts scripts/ on the path)


class ColorSpellingTest(unittest.TestCase):
    def test_common_spellings_read_as_their_code(self) -> None:
        spellings = {"BK": "BK", "blk": "BK", "Black": "BK", "WHT/BLU": "WHBU", "GN/YE": "GNYE", "GNYE": "GNYE",
                     "green-yellow": "GNYE", "white with blue stripe": "WHBU", "RED": "RD", "ORN": "OG", "YEL": "YE",
                     "BRN": "BN", "VIO": "VT", "purple": "VT", "GRY": "GY", "gray": "GY", "grey": "GY", "PNK": "PK",
                     "BL": "BU", "OR": "OG", "VI": "VT", "BR": "BN", "WH BK": "WHBK", "TRQ": "TQ"}
        for written, code in spellings.items():
            with self.subTest(written):
                self.assertEqual(iec_color_code(written), code)

    def test_a_colour_nobody_would_recognise_reads_as_none(self) -> None:
        for written in ("XQ", "BLURPLE", "WHT/XYZ", ""):
            with self.subTest(written):
                self.assertIsNone(iec_color_code(written))


class ColorInSourceTest(unittest.TestCase):
    def generate(self, source: str) -> Path:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        process = run_generator_on_text(source, directory, "--no-wireviz")
        self.assertNotIn("Traceback", process.stderr, process.stderr)
        return directory

    def test_a_spelled_out_colour_is_listed_as_its_code(self) -> None:
        source = example_text("two-wire").replace("color: BK}", "color: BLK}").replace("color: RD}", "color: red}")
        directory = self.generate(source)
        rows = list(csv.DictReader((directory / "harness.wirelist.csv").read_text().splitlines()))
        self.assertEqual([row["color"] for row in rows], ["BK", "RD"])
        self.assertNotIn("colour", (directory / "harness.checks.txt").read_text())

    def test_a_cable_conductor_is_named_by_its_code(self) -> None:
        source = example_text("split-cable").replace("{color: RD, from", "{color: RED, from")
        rows = list(csv.DictReader((self.generate(source) / "harness.wirelist.csv").read_text().splitlines()))
        self.assertIn("W5-RD", [row["wire"] for row in rows])

    def test_an_unrecognised_colour_is_reported_and_drawn_grey(self) -> None:
        source = example_text("two-wire").replace("color: RD}", "color: BLURPLE}")
        directory = self.generate(source)
        self.assertIn("WARN   W2: colour 'BLURPLE' is not a colour this drawing knows; drawn grey",
                      (directory / "harness.checks.txt").read_text())

    def test_a_colour_left_out_is_not_reported(self) -> None:
        source = example_text("two-wire").replace(", color: RD}", "}")
        self.assertNotIn("colour", (self.generate(source) / "harness.checks.txt").read_text())


if __name__ == "__main__":
    unittest.main()
