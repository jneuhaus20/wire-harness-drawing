"""Pinout diagrams put each contact where it is on the real connector, by its real number, seen from the stated side.

The reference for where contacts are is each connector's vertical-mount KiCad footprint (tests/fixtures/kicad/):
standing on the board with its mating face up, its pads seen from above are its mating face seen from the front.
The XLR is the hard case: its contacts are numbered out of order round the face and are not evenly spaced.
"""
import json
import math
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.generator import repository, run_generator

footprints = repository / "tests" / "fixtures" / "kicad"

# (example, connector, footprint whose pads are that connector's contacts, seen from its mating face)
faces = [("xlr-mic-cable", "P1", "Jack_XLR_Neutrik_NC3FAV_Vertical"),
         ("xlr-mic-cable", "P2", "Jack_XLR_Neutrik_NC3MAV_Vertical"),
         ("sensor-branch", "P1", "DSUB-9_Pins_Vertical_P2.77x2.84mm")]


def footprint_pads(name: str) -> dict[str, tuple[float, float]]:
    """A footprint's numbered pads and their positions in mm, y down."""
    text = (footprints / f"{name}.kicad_mod").read_text()
    pads = re.findall(r'\(pad "(\d+)"[^(]*\(at ([-\d.]+) ([-\d.]+)', text)
    return {number: (float(x), float(y)) for number, x, y in pads}


def is_scaled_copy(drawn: dict[str, tuple[float, float]], real: dict[str, tuple[float, float]]) -> bool:
    """Whether the drawn positions are the real ones scaled evenly and moved, never turned or mirrored."""
    if set(drawn) != set(real):
        return False
    first, second = sorted(real, key=lambda pin: real[pin])[:2]
    scale = math.dist(drawn[first], drawn[second]) / math.dist(real[first], real[second])
    offset = (drawn[first][0] - scale * real[first][0], drawn[first][1] - scale * real[first][1])
    return scale > 0 and all(math.dist(drawn[pin], (offset[0] + scale * x, offset[1] + scale * y)) < 0.05 * scale
                             for pin, (x, y) in real.items())


class PinoutFaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        cls.outputs = {}
        for example in {example for example, _, _ in faces}:
            output = Path(cls.directory.name) / example
            run_generator(repository / "examples" / example / f"{example}.yaml", output, "--no-wireviz")
            cls.outputs[example] = output

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def test_the_reference_xlr_is_out_of_order_and_uneven(self) -> None:
        pads = footprint_pads("Jack_XLR_Neutrik_NC3FAV_Vertical")
        self.assertNotEqual(sorted(pads, key=lambda pin: math.atan2(pads[pin][1] + 0.6, pads[pin][0] + 3.81)), ["1", "2", "3"])
        sides = sorted(round(math.dist(pads[a], pads[b]), 2) for a, b in (("1", "2"), ("2", "3"), ("1", "3")))
        self.assertGreater(sides[-1] - sides[0], 1)

    def test_each_source_states_its_connectors_contacts_where_the_footprint_puts_them(self) -> None:
        for example, designator, footprint in faces:
            with self.subTest(f"{example} {designator}"):
                source = yaml.safe_load((repository / "examples" / example / f"{example}.yaml").read_text())
                face = source["connectors"][designator]["face"]
                self.assertEqual(face["view"], "mating face")
                stated = {str(pin): tuple(position) for pin, position in face["cavities"].items()}
                self.assertTrue(is_scaled_copy(stated, footprint_pads(footprint)), stated)

    def test_the_drawings_pinout_puts_each_numbered_contact_where_the_footprint_does(self) -> None:
        for example, designator, footprint in faces:
            with self.subTest(f"{example} {designator}"):
                sheets = "".join(path.read_text() for path in sorted(self.outputs[example].glob("*.sheet*.svg")))
                group = re.search(rf'<g class="pinout" data-connector="{designator}">(.*?)</g>', sheets, re.S)[1]
                circles = re.findall(r'<circle cx="([-\d.]+)" cy="([-\d.]+)"', group)
                labels = re.findall(r'<text[^>]*>([^<]+)</text>', group)[1:]
                drawn = {label: (float(x), float(y)) for label, (x, y) in zip(labels, circles)}
                self.assertTrue(is_scaled_copy(drawn, footprint_pads(footprint)), drawn)
                self.assertIn("MATING FACE", group)

    def test_the_explorer_model_carries_the_same_face(self) -> None:
        for example, designator, footprint in faces:
            with self.subTest(f"{example} {designator}"):
                model = json.loads((self.outputs[example] / f"{example}.harness.json").read_text())
                connector = next(item for item in model["connectors"] if item["id"] == designator)
                drawn = {pin: tuple(position) for pin, position in connector["face"]["cavities"].items()}
                self.assertTrue(is_scaled_copy(drawn, footprint_pads(footprint)), drawn)
                self.assertEqual(connector["face"]["view"], "mating face")


if __name__ == "__main__":
    unittest.main()
