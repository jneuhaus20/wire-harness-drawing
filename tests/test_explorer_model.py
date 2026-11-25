"""The harness model the explorer component draws comes from the same analysis and placement as the drawing."""
import json
import unittest

from tests.generator import example_directory, example_source
from tests.test_output_integrity import generate, two_wire_harness

from harness.explorer_model import harness_model  # noqa: E402  (tests.generator puts scripts/ on the path)
from harness.formboard import sheet_placement
from harness.package import analyse
from harness.source import display_colors, load_source


class ExampleModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.analysis = analyse(load_source(example_source))
        cls.model = harness_model(cls.analysis)

    def test_it_names_its_format_and_the_drawing(self) -> None:
        self.assertEqual(self.model["format"], "wire-harness-explorer/1")
        self.assertEqual((self.model["title"], self.model["number"], self.model["rev"]), ("SENSOR BRANCH HARNESS", "EX-0001", "A"))

    def test_every_connector_and_wire_is_in_it(self) -> None:
        self.assertEqual([c["id"] for c in self.model["connectors"]], list(self.analysis.source["connectors"]))
        self.assertEqual([w["id"] for w in self.model["wires"]], [w["id"] for w in self.analysis.source["wires"]])

    def test_the_2d_placement_is_sheet_ones(self) -> None:
        placement = sheet_placement(self.analysis.source, self.analysis.tree)
        for node in self.model["nodes"]:
            self.assertEqual((node["x"], node["y"]), (round(placement.x[node["id"]], 1), round(placement.y[node["id"]], 1)))

    def test_a_wire_carries_its_ends_colours_length_and_route(self) -> None:
        wire = next(w for w in self.model["wires"] if w["id"] == "W13")
        self.assertEqual((wire["from"], wire["to"]), ({"connector": "P1", "pin": "8"}, {"connector": "E1", "pin": "1"}))
        self.assertEqual(wire["colors"], [display_colors["GN"], display_colors["YE"]])
        self.assertEqual(wire["cut_length"], "470")
        self.assertEqual(wire["route"], ["P1", "B1", "E1"])

    def test_a_connector_carries_its_pins_and_its_stated_face(self) -> None:
        j1 = next(c for c in self.model["connectors"] if c["id"] == "J1")
        self.assertEqual(j1["pins"][2], {"pin": "3", "label": "SCL"})
        self.assertEqual(j1["face"]["view"], "mating face")
        self.assertEqual(j1["face"]["cavities"]["4"], [3, 0])
        e1 = next(c for c in self.model["connectors"] if c["id"] == "E1")
        self.assertIsNone(e1["face"])

    def test_segments_carry_their_dimension_text_and_wires(self) -> None:
        segment = next(s for s in self.model["segments"] if s["nodes"] == ["P1", "B1"])
        self.assertEqual(segment["length"], "300 ±5")
        self.assertTrue(segment["known"])
        self.assertIn("W13", segment["wires"])

    def test_without_routing_geometry_it_says_the_layout_is_schematic(self) -> None:
        self.assertEqual(self.model["geometry"], "schematic")


class ModelFileTest(unittest.TestCase):
    def test_the_written_model_can_be_inlined_in_a_script_element(self) -> None:
        source = two_wire_harness.replace("pinlabels: [GND, VCC]}", "pinlabels: [GND, </script>]}", 1)
        written = generate(self, source).read("harness.json")
        self.assertNotIn("</", written)
        self.assertIn("</script>", json.dumps(json.loads(written)).replace("\\/", "/"))

    def test_the_package_writes_the_model_beside_the_sheets(self) -> None:
        written = json.loads(generate(self, None).read("harness.json"))
        self.assertEqual(written, json.loads((example_directory / "sensor-branch.harness.json").read_text()))


if __name__ == "__main__":
    unittest.main()
