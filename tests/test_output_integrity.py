"""The package never looks more finished or more certain than its source allows."""
import csv
import html
import re
import tempfile
import unittest
from pathlib import Path

from tests.generator import example_source, run_generator, run_generator_on_text

from harness import svg  # noqa: E402  (tests.generator puts scripts/ on the path)

two_wire_harness = """
drawing: {title: TWO WIRE, number: T-1, rev: A}
connectors:
  P1: {type: KK 254, pincount: 2, pinlabels: [GND, VCC]}
  J1: {type: KK 254, pincount: 2, pinlabels: [GND, VCC]}
wires:
  - {id: W1, from: "P1:1", to: "J1:1", signal: GND, gauge: 24 AWG, color: BK}
  - {id: W2, from: "P1:2", to: "J1:2", signal: VCC, gauge: 24 AWG, color: RD}
layout:
  root: P1
  segments: [[P1, J1, 500]]
"""


# A trunk with a breakout every 100 mm and a 4-pin connector on each branch: more
# leaves than one sheet holds.
def ten_branch_harness() -> str:
    """Return the source of a harness with ten branches off one trunk."""
    connectors = ["  P1: {type: DE-9, pincount: 10}"]
    wires = []
    segments = []
    for branch in range(1, 11):
        connectors.append(f"  J{branch}: {{type: KK 254, pincount: 1}}")
        wires.append(f'  - {{id: W{branch}, from: "P1:{branch}", to: "J{branch}:1", gauge: 24 AWG, color: BK}}')
        previous = "P1" if branch == 1 else f"B{branch - 1}"
        segments.append(f"    - [{previous}, B{branch}, 100]")
        segments.append(f"    - [B{branch}, J{branch}, 200]")
    return "\n".join(["drawing: {title: TEN BRANCH, number: T-10, rev: A}", "connectors:", *connectors,
                      "wires:", *wires, "layout:", "  root: P1", "  segments:", *segments, ""])


class GeneratedPackage:
    """One generator run in a temporary directory, with its outputs read back."""

    def __init__(self, source_text: str | None) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        if source_text is None:
            self.process = run_generator(example_source, self.directory, "--no-wireviz")
            self.base = "example"
        else:
            self.process = run_generator_on_text(source_text, self.directory, "--no-wireviz")
            self.base = "harness"

    def read(self, suffix: str) -> str:
        return (self.directory / f"{self.base}.{suffix}").read_text()

    def sheets(self) -> list[str]:
        return [path.read_text() for path in sorted(self.directory.glob(f"{self.base}.sheet*.svg"))]

    def bom_rows(self) -> list[dict[str, str]]:
        return list(csv.DictReader(self.read("bom.csv").splitlines()))

    def close(self) -> None:
        self.temporary_directory.cleanup()


def generate(test: unittest.TestCase, source_text: str | None) -> GeneratedPackage:
    """Run the generator on a source (None for the shipped example) and clean up after the test."""
    package = GeneratedPackage(source_text)
    test.addCleanup(package.close)
    return package


def svg_texts(svg: str) -> list[str]:
    return [html.unescape(content) for content in re.findall(r"<text[^>]*>([^<]*)</text>", svg)]


class FailedChecksMarkTheSheetsTest(unittest.TestCase):
    def test_every_sheet_of_a_package_with_errors_says_it_is_not_for_release(self) -> None:
        package = generate(self, two_wire_harness + "expect: {nets: {GND: [P1:1, J1:2]}}\n")
        self.assertEqual(package.process.returncode, 1)
        for number, sheet in enumerate(package.sheets(), 1):
            self.assertIn("NOT FOR RELEASE", sheet, f"sheet {number}")

    def test_a_package_without_errors_carries_no_release_mark(self) -> None:
        package = generate(self, two_wire_harness)
        self.assertEqual(package.process.returncode, 0, package.read("checks.txt"))
        for number, sheet in enumerate(package.sheets(), 1):
            self.assertNotIn("NOT FOR RELEASE", sheet, f"sheet {number}")


class DrawingFitsTheSheetTest(unittest.TestCase):
    def test_a_drawing_too_big_for_the_sheet_is_an_error(self) -> None:
        package = generate(self, ten_branch_harness())
        checks = package.read("checks.txt")
        self.assertRegex(checks, r"ERROR .*does not fit", checks)
        self.assertIn("NOT FOR RELEASE", package.sheets()[0])

    def test_check_only_reports_the_misfit_too(self) -> None:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        process = run_generator_on_text(ten_branch_harness(), directory, "--check-only")
        self.assertEqual(process.returncode, 1)
        self.assertIn("does not fit", process.stdout)

    def test_the_example_and_a_small_harness_fit(self) -> None:
        for source in (None, two_wire_harness):
            self.assertNotIn("does not fit", generate(self, source).read("checks.txt"))


class TableTextIsCompleteTest(unittest.TestCase):
    long_text_harness = two_wire_harness.replace(
        "P1: {type: KK 254,",
        "P1: {desc: 'Receptacle housing, dual row, 2 position, polarized, with positive latch and TPA, glow-wire rated',"
        " pn: WWWWWWWWWWWWWWWWWWWWWWWWWW-1, type: KK 254,")

    def test_no_cell_is_cut_short(self) -> None:
        sheets = generate(self, self.long_text_harness).sheets()
        for sheet in sheets[1:]:
            self.assertNotIn("…", sheet)
        table_words = " ".join(" ".join(svg_texts(sheet)) for sheet in sheets[1:]).split()
        for word in "Receptacle housing, dual row, polarized, positive latch TPA, glow-wire rated".split():
            self.assertIn(word, table_words)
        self.assertIn("WWWWWWWWWWWWWWWWWWWWWWWWWW-1", "".join(table_words))

    def test_the_example_sleeving_references_are_all_listed(self) -> None:
        table_text = " ".join(svg_texts(generate(self, None).sheets()[1]))
        for segment in ("P1-B1", "B1-SP1", "SP1-SP2", "SP2-SP3", "SP3-SP4", "SP4-B2"):
            self.assertIn(segment, table_text)

    def test_every_cell_line_fits_inside_its_cell(self) -> None:
        cells = [("FIND", 40, "c"), ("DESCRIPTION", 120, "l")]
        rows = [[7, "Receptacle housing, dual row, polarized, positive latch, WWWWWWWWWWWWWWWWWWWWWWWW"]]
        drawn, height, used = svg.table(0, 0, cells, rows, "A TABLE TITLE LONGER THAN BOTH OF ITS COLUMNS")
        self.assertEqual(used, 1)
        rectangles = [tuple(map(float, found)) for found in
                      re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', drawn)]
        texts = re.findall(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*font-size="([\d.]+)" text-anchor="(\w+)" '
                           r'font-weight="(\w+)"[^>]*>([^<]*)</text>', drawn)
        self.assertGreater(len(texts), 4)
        for x, y, size, anchor, weight, content in texts:
            x, y, size = float(x), float(y), float(size)
            width = svg.text_width(html.unescape(content), size, weight == "bold")
            left = x if anchor == "start" else x - width / 2
            cell = min((r for r in rectangles if r[0] <= x <= r[0] + r[2] and r[1] <= y - 2 <= r[1] + r[3]),
                       key=lambda r: r[2] * r[3])
            self.assertGreaterEqual(left, cell[0], content)
            self.assertLessEqual(left + width, cell[0] + cell[2], content)
            self.assertLessEqual(y, cell[1] + cell[3], content)
        self.assertEqual(height, max(r[1] + r[3] for r in rectangles))

    def test_text_width_uses_helvetica_metrics(self) -> None:
        self.assertAlmostEqual(svg.text_width("M", 10, False), 8.33)
        self.assertAlmostEqual(svg.text_width("il", 10, False), 4.44)
        self.assertAlmostEqual(svg.text_width("b", 10, True), 6.11)


class BillOfMaterialsTest(unittest.TestCase):
    def test_wires_of_different_type_are_separate_lines(self) -> None:
        source = two_wire_harness.replace("signal: GND, gauge: 24 AWG, color: BK}",
                                          "signal: GND, gauge: 24 AWG, color: BK, type: UL1007}")
        source = source.replace("signal: VCC, gauge: 24 AWG, color: RD}",
                                "signal: VCC, gauge: 24 AWG, color: BK, type: UL1015}")
        wire_lines = [row for row in generate(self, source).bom_rows() if "AWG" in row["description"]]
        self.assertEqual(sorted(row["description"] for row in wire_lines), ["UL1007, 24 AWG, BK", "UL1015, 24 AWG, BK"])
        self.assertEqual([row["refs"] for row in wire_lines if "UL1007" in row["description"]], ["W1"])

    def test_a_length_through_a_tbd_segment_is_tbd_not_zero(self) -> None:
        source = """
drawing: {title: TBD, number: T-2, rev: A}
connectors:
  P1: {type: KK 254, pincount: 2}
  J1: {type: KK 254, pincount: 1}
  J2: {type: KK 254, pincount: 1}
wires:
  - {id: W1, from: "P1:1", to: "J1:1", gauge: 24 AWG, color: BK}
  - {id: W2, from: "P1:2", to: "J2:1", gauge: 24 AWG, color: RD}
layout:
  root: P1
  segments: [[P1, B1, 300], [B1, J1, TBD], [B1, J2, 200]]
  coverings:
    - {item: SLV, segments: [P1-B1, B1-J1]}
    - {item: SLV2, segments: [B1-J2]}
items:
  - {id: SLV, desc: Sleeving A, qty: AR, unit: m}
  - {id: SLV2, desc: Sleeving B, qty: AR, unit: m}
  - {id: HS, desc: Heat-shrink, qty: AR, unit: m}
"""
        quantities = {row["description"]: row["qty"] for row in generate(self, source).bom_rows()}
        self.assertEqual(quantities["Hook-up wire, 24 AWG, BK"], "TBD")
        self.assertEqual(quantities["Hook-up wire, 24 AWG, RD"], "0.5")
        self.assertEqual(quantities["Sleeving A"], "TBD")
        self.assertEqual(quantities["Sleeving B"], "0.2")
        self.assertEqual(quantities["Heat-shrink"], "AR")

    def test_inch_lengths_buy_in_feet(self) -> None:
        source = two_wire_harness.replace("rev: A}", "rev: A, units: in, round_to: 1}").replace("500]", "24]")
        package = generate(self, source)
        wire_lines = [row for row in package.bom_rows() if "AWG" in row["description"]]
        self.assertEqual([(row["qty"], row["unit"]) for row in wire_lines], [("2", "ft"), ("2", "ft")])

    def test_inch_drawings_default_to_inch_tolerances(self) -> None:
        source = two_wire_harness.replace("rev: A}", "rev: A, units: in, round_to: 1}").replace("500]", "24]")
        drawing_text = svg_texts(generate(self, source).sheets()[0])
        self.assertIn("24 ±0.5", drawing_text)

    def test_units_other_than_mm_or_in_are_an_error(self) -> None:
        source = two_wire_harness.replace("rev: A}", "rev: A, units: cm}")
        self.assertRegex(generate(self, source).read("checks.txt"), r"ERROR .*units")


class DimensionsTest(unittest.TestCase):
    def test_overall_dimensions_are_reference_and_chain_dimensions_carry_tolerance(self) -> None:
        drawing_text = svg_texts(generate(self, None).sheets()[0])
        overall = [label for label in drawing_text if "(P1–" in label]
        self.assertEqual(len(overall), 4, drawing_text)
        for label in overall:
            self.assertIn("REF", label)
            self.assertNotIn("±", label)
        self.assertIn("300 ±5", drawing_text)
        self.assertTrue(any("OVERALL" in line and "REFERENCE" in line for line in drawing_text))


class YamlWordsStayWordsTest(unittest.TestCase):
    relay_harness = """
drawing: {title: RELAY, number: T-3, rev: A}
connectors:
  K1: {type: relay socket, pincount: 3, pinlabels: [COM, NO, NC]}
  J1: {type: KK 254, pincount: 3, pinlabels: [COM, NO, NC]}
wires:
  - {id: W1, from: "K1:1", to: "J1:1", signal: COM, gauge: 24 AWG, color: BK}
  - {id: W2, from: "K1:2", to: "J1:2", signal: OFF, gauge: 24 AWG, color: RD}
  - {id: W3, from: "K1:3", to: "J1:3", signal: NC, gauge: 24 AWG, color: BU}
layout:
  root: K1
  segments: [[K1, J1, 300]]
"""

    def test_unquoted_no_and_off_load_as_text(self) -> None:
        package = generate(self, self.relay_harness)
        self.assertIn("signal 'OFF' but K1:2 is labelled 'NO'", package.read("checks.txt"))
        self.assertIn("W2,K1,2,J1,2,OFF,", package.read("wirelist.csv"))

    def test_true_and_false_still_load_as_booleans(self) -> None:
        source = two_wire_harness.replace("P1: {type: KK 254,", "P1: {sealed: true, type: KK 254,")
        self.assertNotIn("sealing plugs", generate(self, source).read("checks.txt"))
        source = two_wire_harness.replace("P1: {type: KK 254, pincount: 2,", "P1: {sealed: true, type: KK 254, pincount: 3,")
        self.assertIn("sealing plugs", generate(self, source).read("checks.txt"))


if __name__ == "__main__":
    unittest.main()


class CheckOnlyLaysOutTheDrawingSafelyTest(unittest.TestCase):
    """--check-only now lays out sheet 1, which must not turn reportable inputs into tracebacks."""

    def assert_check_only_runs(self, source_text: str) -> None:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        process = run_generator_on_text(source_text, directory, "--check-only")
        self.assertNotIn("Traceback", process.stderr, process.stderr)

    def test_a_numeric_gauge(self) -> None:
        self.assert_check_only_runs(two_wire_harness.replace("gauge: 24 AWG, color: BK", "gauge: 24, color: BK"))

    def test_a_covering_on_an_unknown_node(self) -> None:
        self.assert_check_only_runs(two_wire_harness + "  coverings: [{item: SLV, segments: [P1-X9]}]\n"
                                    "items: [{id: SLV, desc: Sleeving, qty: AR, unit: m}]\n")

    def test_an_empty_items_list(self) -> None:
        self.assert_check_only_runs(two_wire_harness + "items:\n")
