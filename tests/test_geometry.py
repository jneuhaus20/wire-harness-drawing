"""Optional fixed routing geometry: checked against the lengths, drawn to scale, and carried to the explorer."""
import math
import tempfile
import unittest
from pathlib import Path

from tests.generator import run_generator_on_text
from tests.test_output_integrity import generate, svg_texts

from harness.explorer_model import harness_model  # noqa: E402  (tests.generator puts scripts/ on the path)
from harness.package import analyse
from harness.source import load_source

# E1's branch leaves B1 straight down, then bends toward the right: 100 + 111.8 + 38.2 = 250.
routed_harness = """
drawing: {title: ROUTED, number: T-6, rev: A}
connectors:
  P1: {type: KK 254, pn: A-1, pincount: 2}
  J1: {type: KK 254, pn: A-2, pincount: 1}
  E1: {type: Ring lug, pn: A-3, pincount: 1}
wires:
  - {id: W1, from: "P1:1", to: "J1:1", gauge: 24 AWG, color: BK}
  - {id: W2, from: "P1:2", to: "E1", gauge: 24 AWG, color: GNYE}
layout:
  root: P1
  nodes: {P1: [0, 0], B1: [300, 0], J1: [600, 0], E1: [438.197, 150]}
  segments:
    - [P1, B1, 300]
    - [B1, J1, 300]
    - [B1, E1, 250, {via: [[300, 100], [400, 150]]}]
"""

routed_3d_harness = routed_harness.replace(
    "nodes: {P1: [0, 0], B1: [300, 0], J1: [600, 0], E1: [438.197, 150]}",
    "nodes: {P1: [0, 0, 0], B1: [300, 0, 0], J1: [600, 0, 0], E1: [438.197, 150, 0]}").replace(
    "via: [[300, 100], [400, 150]]", "via: [[300, 100, 0], [400, 150, 0]]")


def findings_for(test: unittest.TestCase, source: str) -> str:
    directory = Path(test.enterContext(tempfile.TemporaryDirectory()))
    process = run_generator_on_text(source, directory, "--check-only")
    test.assertNotIn("Traceback", process.stderr, process.stderr)
    return (directory / "harness.checks.txt").read_text()


def model_for(test: unittest.TestCase, source: str) -> dict:
    directory = Path(test.enterContext(tempfile.TemporaryDirectory()))
    (directory / "harness.yaml").write_text(source)
    return harness_model(analyse(load_source(directory / "harness.yaml")))


class GeometryChecksTest(unittest.TestCase):
    def test_a_route_that_matches_its_lengths_is_clean(self) -> None:
        self.assertEqual(findings_for(self, routed_harness), "OK     no findings\n")

    def test_a_route_longer_than_its_tolerance_allows_is_an_error(self) -> None:
        findings = findings_for(self, routed_harness.replace("[B1, J1, 300]", "[B1, J1, 280]"))
        self.assertIn("ERROR  layout segment B1-J1: its route is 300 long, but its length is 280 ±5", findings)

    def test_an_unknown_length_is_taken_from_the_route(self) -> None:
        source = routed_harness.replace("[B1, J1, 300]", "[B1, J1, TBD]")
        self.assertIn("INFO   layout segment B1-J1: length taken from its route, 300", findings_for(self, source))
        cut = generate(self, source).read("wirelist.csv").splitlines()[1].split(",")[8]
        self.assertEqual(cut, "600")

    def test_every_node_needs_a_position(self) -> None:
        source = routed_harness.replace(", E1: [438.197, 150]", "")
        self.assertIn("ERROR  layout.nodes gives no position for E1; give every node one, or none", findings_for(self, source))

    def test_positions_are_all_2d_or_all_3d(self) -> None:
        source = routed_harness.replace("J1: [600, 0]", "J1: [600, 0, 0]")
        self.assertIn("ERROR  layout.nodes mixes 2D and 3D positions", findings_for(self, source))

    def test_a_via_point_has_the_nodes_dimensions(self) -> None:
        source = routed_harness.replace("via: [[300, 100], [400, 150]]", "via: [[300, 100, 5], [400, 150]]")
        self.assertIn("ERROR  layout segment B1-E1: via point [300, 100, 5] is not a 2D position", findings_for(self, source))


class ToScaleSheetTest(unittest.TestCase):
    def test_sheet_one_is_drawn_to_a_standard_scale_and_says_so(self) -> None:
        texts = svg_texts(generate(self, routed_harness).sheets()[0])
        scale = next(text for text in texts if text.startswith("1:"))
        self.assertIn(scale, {f"1:{k}" for k in (1, 2, 2.5, 4, 5, 10, 20, 25, 50, 100, 200)})
        notes = " ".join(texts)
        self.assertNotIn("NOT TO SCALE", notes)
        self.assertIn(f"DRAWN TO SCALE {scale} ON A3; DIMENSIONS GOVERN.", notes)

    def test_the_sheet_keeps_the_routes_proportions(self) -> None:
        nodes = {node["id"]: (node["x"], node["y"]) for node in model_for(self, routed_harness)["nodes"]}
        unit = (nodes["B1"][0] - nodes["P1"][0]) / 300
        self.assertAlmostEqual((nodes["J1"][0] - nodes["B1"][0]) / 300, unit, places=2)
        self.assertAlmostEqual((nodes["E1"][1] - nodes["B1"][1]) / 150, unit, places=2)
        self.assertAlmostEqual(nodes["P1"][1], nodes["J1"][1], places=1)

    def test_the_drawing_still_reads_cleanly(self) -> None:
        self.assertEqual(generate(self, routed_harness).process.returncode, 0)


class GeometryModelTest(unittest.TestCase):
    def test_a_2d_route_reaches_the_explorer_in_true_units(self) -> None:
        model = model_for(self, routed_harness)
        self.assertEqual(model["geometry"], "2d")
        branch = next(segment for segment in model["segments"] if segment["nodes"] == ["B1", "E1"])
        self.assertEqual(branch["points"], [[300, 0, 0], [300, 0, 100], [400, 0, 150], [438.197, 0, 150]])
        lengths = [math.dist(a, b) for a, b in zip(branch["points"], branch["points"][1:])]
        self.assertAlmostEqual(sum(lengths), 250, places=2)

    def test_a_3d_route_keeps_its_height(self) -> None:
        source = routed_3d_harness.replace("[300, 100, 0]", "[300, 100, 40]").replace("250, {via", "257.3, {via")
        model = model_for(self, source)
        self.assertEqual(model["geometry"], "3d")
        branch = next(segment for segment in model["segments"] if segment["nodes"] == ["B1", "E1"])
        self.assertEqual(branch["points"][1], [300, 40, 100])

    def test_sheet_one_draws_a_3d_route_flattened_as_on_the_board(self) -> None:
        texts = svg_texts(generate(self, routed_3d_harness).sheets()[0])
        notes = " ".join(texts)
        self.assertIn("THE 3D ROUTE IS SHOWN FLATTENED, AS LAID ON THE FORMBOARD", notes)
        self.assertIn("NOT TO SCALE", notes)
        self.assertIn("550 REF  (P1–E1)", texts)

    def test_a_3d_route_with_a_vertical_run_still_draws(self) -> None:
        source = routed_3d_harness.replace("B1: [300, 0, 0]", "B1: [300, 0, 0], B2: [300, 0, -80]").replace(
            "[P1, B1, 300]", "[P1, B1, 300]\n    - [B1, B2, 80]").replace("[B1, E1, 250, {via", "[B2, E1, 170, {via").replace(
            "via: [[300, 100, 0], [400, 150, 0]]", "via: [[300, 0, 0], [300, 100, 0]]")
        self.assertNotIn("Traceback", generate(self, source).process.stderr)


if __name__ == "__main__":
    unittest.main()
