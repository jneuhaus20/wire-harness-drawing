"""The sheets read cleanly: nothing printed over anything else, nothing said twice, nothing left off."""
import re
import tempfile
import unittest
from pathlib import Path

from tests.generator import example_source
from tests.test_geometry import routed_harness
from tests.test_output_integrity import generate, svg_texts, two_wire_harness

from harness.source import display_colors  # noqa: E402  (tests.generator puts scripts/ on the path)
from harness.package import analyse
from harness.source import load_source
from harness.wiring import wireviz_source


def lay_out_sheet_one(source: Path):
    """Run the generator's pipeline on a source and return sheet 1's layout record."""
    return analyse(load_source(source)).sheet_layout


def boxes_overlap(first, second) -> bool:
    return first[0] < second[2] and second[0] < first[2] and first[1] < second[3] and second[1] < first[3]


# Liang–Barsky clipping: does the segment pass through the inside of the box?
def segment_crosses_box(segment, box) -> bool:
    (x1, y1, x2, y2), (left, top, right, bottom) = segment, box
    start, end = 0.0, 1.0
    for p, q in ((-(x2 - x1), x1 - left), (x2 - x1, right - x1), (-(y2 - y1), y1 - top), (y2 - y1, bottom - y1)):
        if p == 0:
            if q <= 0:
                return False
            continue
        r = q / p
        if p < 0:
            start = max(start, r)
        else:
            end = min(end, r)
        if start >= end:
            return False
    return end - start > 1e-6


class ExampleSheetOneLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.layout = lay_out_sheet_one(example_source)

    def test_no_text_is_printed_over_other_text(self) -> None:
        texts = self.layout.texts
        clashes = [(a, b) for i, (a, box_a) in enumerate(texts) for b, box_b in texts[i + 1:] if boxes_overlap(box_a, box_b)]
        self.assertEqual(clashes, [])

    def test_no_leader_crosses_text_or_a_dimension_line(self) -> None:
        crossings = [(leader, what) for leader, segment, exempt in self.layout.leaders
                     for what, box in self.layout.texts + self.layout.dimension_lines
                     if what not in exempt and segment_crosses_box(segment, box)]
        self.assertEqual(crossings, [])

    def test_no_extension_line_crosses_text(self) -> None:
        crossings = [(extension, what) for extension, segment, exempt in self.layout.extension_lines
                     for what, box in self.layout.texts
                     if what not in exempt and segment_crosses_box(segment, box)]
        self.assertEqual(crossings, [])


class RoutedSheetOneLayoutTest(ExampleSheetOneLayoutTest):
    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "harness.yaml").write_text(routed_harness)
            cls.layout = lay_out_sheet_one(Path(directory) / "harness.yaml")


class FrameTest(unittest.TestCase):
    def test_the_revision_block_leaves_the_zone_numbers_visible(self) -> None:
        sheet = generate(self, None).sheets()[0]
        zone_numbers = re.findall(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>([1-8])</text>', sheet)
        top = [(float(x), number) for x, y, number in zone_numbers if float(y) < 40]
        self.assertEqual(sorted(number for _, number in top), list("12345678"))
        revisions = re.search(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="[\d.]+" fill="#e8e8e8"', sheet)
        self.assertGreaterEqual(float(revisions.group(2)), 30)

    def test_not_to_scale_is_said_once_on_the_drawing(self) -> None:
        drawing_text = " ".join(svg_texts(generate(self, None).sheets()[0]))
        self.assertEqual(drawing_text.count("NOT TO SCALE"), 1)


class WireRenderingTest(unittest.TestCase):
    def test_a_striped_wire_draws_both_colours(self) -> None:
        sheet = generate(self, None).sheets()[0]
        yellow_stripes = re.findall(rf'<path [^>]*stroke="{display_colors["YE"]}"[^>]*stroke-dasharray', sheet)
        self.assertEqual(len(yellow_stripes), 2, "W13 GNYE at P1 and at E1")


class TablesTest(unittest.TestCase):
    def test_connector_descriptions_state_the_pin_count_once(self) -> None:
        descriptions = [row["description"] for row in generate(self, None).bom_rows()]
        self.assertIn("KK 254 female 4-pin", descriptions)
        self.assertIn("DE-9 plug, male, solder cup, 9 pos", descriptions)
        self.assertIn("Ring lug #6 stud, vinyl insulated, 22-18 AWG", descriptions)

    def test_the_wire_list_sheet_gives_find_numbers_and_strip_lengths(self) -> None:
        source = two_wire_harness.replace("P1: {type", "P1: {strip: 3, type").replace("J1: {type", "J1: {strip: 4, type")
        package = generate(self, source)
        sheet = package.sheets()[1]
        self.assertIn(">FIND<", sheet)
        self.assertEqual(sheet.count(">STRIP<"), 2)
        black_wire_find = next(row["find"] for row in package.bom_rows() if row["description"].endswith("BK"))
        wire_list = sheet[sheet.index(">WIRE LIST (FROM"):]
        first_row = svg_texts(wire_list)[14:28]
        self.assertEqual(first_row[:6], ["W1", black_wire_find, "P1", "1", "3", "GND"])
        self.assertIn("4", first_row)


twisted_harness = two_wire_harness.replace("color: BK}", "color: BK, twist: T1}").replace("color: RD}", "color: RD, twist: T1}")


class TwistTest(unittest.TestCase):
    def test_twisted_wires_are_cut_longer_by_the_take_up(self) -> None:
        lengths = {row.split(",")[0]: row.split(",")[8] for row in generate(self, twisted_harness).read("wirelist.csv").splitlines()[1:]}
        self.assertEqual(lengths, {"W1": "515", "W2": "515"})
        source = twisted_harness.replace("rev: A}", "rev: A, twist_takeup: 4%}")
        lengths = {row.split(",")[0]: row.split(",")[8] for row in generate(self, source).read("wirelist.csv").splitlines()[1:]}
        self.assertEqual(lengths, {"W1": "520", "W2": "520"})

    def test_the_take_up_is_stated_in_the_notes(self) -> None:
        drawing_text = " ".join(svg_texts(generate(self, twisted_harness).sheets()[0]))
        self.assertIn("TWISTED WIRE CUT LENGTHS INCLUDE 3% TAKE-UP", drawing_text)

    def test_take_up_applies_only_where_the_wires_run_together(self) -> None:
        source = """
drawing: {title: T, number: T, rev: A, round_to: 1}
connectors:
  P1: {type: KK, pincount: 2}
  J1: {type: KK, pincount: 1}
  J2: {type: KK, pincount: 1}
wires:
  - {id: W1, from: "P1:1", to: "J1:1", gauge: 24 AWG, color: BK, twist: T1}
  - {id: W2, from: "P1:2", to: "J2:1", gauge: 24 AWG, color: RD, twist: T1}
layout:
  root: P1
  segments: [[P1, B1, 1000], [B1, J1, 100], [B1, J2, 200]]
"""
        lengths = {row.split(",")[0]: row.split(",")[8] for row in generate(self, source).read("wirelist.csv").splitlines()[1:]}
        self.assertEqual(lengths, {"W1": "1130", "W2": "1230"})


class WiringDiagramTest(unittest.TestCase):
    def wireviz_source(self, source_text: str) -> dict:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (directory / "harness.yaml").write_text(source_text)
        analysis = analyse(load_source(directory / "harness.yaml"))
        return wireviz_source(analysis.source, analysis.routes)

    def test_a_twist_group_is_its_own_labelled_bundle(self) -> None:
        cables = self.wireviz_source(twisted_harness)["cables"]
        self.assertEqual(list(cables), ["T1"])
        self.assertEqual(cables["T1"]["wirelabels"], ["W1", "W2"])
        self.assertEqual(cables["T1"]["type"], "Twisted pair")
        self.assertTrue(cables["T1"]["show_name"])

    def test_lengths_are_given_in_the_unit_wire_is_bought_in(self) -> None:
        source = two_wire_harness.replace("rev: A}", "rev: A, units: in, round_to: 1}").replace("500]", "24]")
        bundle = self.wireviz_source(source)["cables"]["P1-J1"]
        self.assertEqual((bundle["length"], bundle["length_unit"]), (2, "ft"))
        self.assertEqual(self.wireviz_source(two_wire_harness)["cables"]["P1-J1"]["length"], 0.5)

    def test_bundle_names_never_reuse_a_layout_name(self) -> None:
        names = set(self.wireviz_source(example_source.read_text())["cables"])
        layout_names = {node for segment in load_source(example_source)["layout"]["segments"] for node in segment[:2]}
        self.assertFalse(names & layout_names, names & layout_names)
        self.assertIn("SP1-J1", names)

    def test_a_cable_is_drawn_as_that_cable(self) -> None:
        source = two_wire_harness.split("wires:")[0] + """cables:
  C1:
    desc: 2-conductor shielded
    pn: 1234-02
    manufacturer: Alpha
    shield: true
    gauge: 24 AWG
    conductors:
      - {color: BK, from: "P1:1", to: "J1:1", signal: GND}
      - {color: RD, from: "P1:2", to: "J1:2", signal: VCC}
layout:
  root: P1
  segments: [[P1, J1, 500]]
"""
        wireviz = self.wireviz_source(source)
        cable = wireviz["cables"]["C1"]
        self.assertNotEqual(cable.get("category"), "bundle")
        self.assertEqual(cable["pn"], "1234-02")
        self.assertEqual(cable["wirecount"], 2)
        self.assertTrue(cable["shield"])
        self.assertEqual(wireviz["connections"], [[{"P1": [1, 2]}, {"C1": [1, 2]}, {"J1": [1, 2]}]])


if __name__ == "__main__":
    unittest.main()
