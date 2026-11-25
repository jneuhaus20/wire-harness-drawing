"""The TAZ 6 example is LulzBot's harness: its package agrees with LulzBot's own drawing, read from the drawing file.

LulzBot drawing EL-HR0091 rev A (TAZ6_Y-Z_Harness.odg) and drawing EL-HR0143 (whose parts list names the
supplier part behind each LulzBot part number) are committed under examples/taz6-y-z/lulzbot/, CC BY-SA 4.0.
"""
import csv
import re
import tempfile
import unittest
import zipfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from tests.generator import repository, run_generator

example = repository / "examples" / "taz6-y-z"
lulzbot_drawing = example / "lulzbot" / "TAZ6_Y-Z_Harness.odg"
lulzbot_parts_drawing = example / "lulzbot" / "EL-HR0143_Y-Z_Harness.pdf"

# The drawing's stroke colours for its conductors. The cable, General Cable (Carol) C0762A, has black,
# white, red and green conductors (its data sheet, as LulzBot hosts it:
# https://devel.lulzbot.com/TAZ/Juniperbush/production_parts/Electronics/Cable_4Cond%20Shielded.pdf),
# so the light grey stroke is the white conductor drawn on a white page.
stroke_colours = {"#000000": "BK", "#cccccc": "WH", "#ff0000": "RD", "#00cc00": "GN"}


@dataclass
class DrawnText:
    text: str
    x: float
    y: float  # the centre of the text box


@dataclass
class DrawnLine:
    colour: str
    start: tuple[float, float]
    end: tuple[float, float]


def centimetres(value: str) -> float:
    return float(value.removesuffix("cm"))


def read_drawing(path: Path) -> tuple[list[DrawnText], list[DrawnLine]]:
    """The text boxes and coloured lines of an OpenDocument drawing, in centimetres."""
    content = zipfile.ZipFile(path).read("content.xml").decode()
    strokes = dict(re.findall(r'<style:style style:name="([^"]+)"(?:(?!</style:style>).)*?svg:stroke-color="(#[0-9a-f]{6})"',
                              content, re.S | re.I))
    texts = []
    for attributes, body in re.findall(r"<draw:frame\b([^>]*)>(.*?)</draw:frame>", content, re.S):
        box = dict(re.findall(r'svg:(x|y|width|height)="([^"]+)"', attributes))
        text = " ".join(re.sub(r"<[^>]+>", " ", body).split())
        if text and {"x", "y", "height"} <= set(box):
            texts.append(DrawnText(text, centimetres(box["x"]), centimetres(box["y"]) + centimetres(box["height"]) / 2))
    lines = []
    for attributes in re.findall(r"<draw:line\b([^>]*)>", content):
        values = dict(re.findall(r'(svg:x1|svg:y1|svg:x2|svg:y2|draw:style-name)="([^"]+)"', attributes))
        colour = strokes.get(values.get("draw:style-name", ""), "").lower()
        if colour in stroke_colours:
            start = (centimetres(values["svg:x1"]), centimetres(values["svg:y1"]))
            end = (centimetres(values["svg:x2"]), centimetres(values["svg:y2"]))
            lines.append(DrawnLine(colour, *sorted([start, end])))
    return texts, lines


@dataclass
class DrawnCable:
    length: int
    strips: list[str]
    sleeving: int
    conductors: set[tuple[str, str, str]]  # (16-way pin, motor-plug pin, colour code)
    drain_pin: str


# The drawing lays its three cables out in bands down the sheet, each headed by its "Length =" text;
# the 16-way plug's pins are labelled on the left, each motor plug's on the right.
def drawn_cables(texts: list[DrawnText], lines: list[DrawnLine]) -> list[DrawnCable]:
    """Each cable LulzBot's drawing shows, top to bottom."""
    heads = sorted((text for text in texts if text.text.startswith("Length =")), key=lambda text: text.y)
    tops = [head.y - 0.8 for head in heads]

    def band(y: float) -> int:
        """The cable band a height on the sheet is in; -1 above the first."""
        return max((index for index, top in enumerate(tops) if top <= y), default=-1)

    pins = [text for text in texts if re.fullmatch(r"Pin \d+", text.text)]
    middle = sum(text.x for text in pins) / len(pins)

    def nearest_pin(x: float, y: float) -> str:
        side = [text for text in pins if (text.x < middle) == (x < middle) and band(text.y) == band(y)]
        return min(side, key=lambda text: abs(text.y - y)).text.split()[1]

    cables = []
    for index, head in enumerate(heads):
        mine = [line for line in lines if band(line.start[1]) == index]
        left = [line for line in mine if line.start[0] < middle - 1]
        right = [line for line in mine if line.end[0] > middle + 1]
        drain_text = next(text for text in texts if text.text == "Bare shield wire" and band(text.y) == index)
        drain_pin = nearest_pin(0, drain_text.y)
        conductors = set()
        for line in right:
            plug_pins = [nearest_pin(*other.start) for other in left if other.colour == line.colour]
            plug_pins = [pin for pin in plug_pins if pin != drain_pin]
            conductors.add((plug_pins[0], nearest_pin(*line.end), stroke_colours[line.colour]))
        sleeving = next(text for text in texts if text.text.startswith("Panduit Jacket") and band(text.y) == index)
        cables.append(DrawnCable(int(re.search(r"(\d+)mm", head.text)[1]),
                                 sorted(text.text for text in texts if text.text.startswith("Strip") and band(text.y) == index),
                                 int(re.search(r"Length=(\d+)mm", sleeving.text)[1]), conductors, drain_pin))
    return cables


class LulzBotDrawingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.texts, lines = read_drawing(lulzbot_drawing)
        cls.drawn = drawn_cables(cls.texts, lines)
        cls.directory = tempfile.TemporaryDirectory()
        output = Path(cls.directory.name)
        run_generator(example / "taz6-y-z.yaml", output, "--no-wireviz")
        cls.cables = list(csv.DictReader((output / "taz6-y-z.cables.csv").read_text().splitlines()))
        cls.wires = list(csv.DictReader((output / "taz6-y-z.wirelist.csv").read_text().splitlines()))
        cls.bom = list(csv.DictReader((output / "taz6-y-z.bom.csv").read_text().splitlines()))
        cls.source = yaml.safe_load((example / "taz6-y-z.yaml").read_text())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def test_the_drawing_is_read_as_three_cables(self) -> None:
        self.assertEqual([cable.length for cable in self.drawn], [240, 430, 615])

    def test_each_cable_is_cut_to_the_drawings_length(self) -> None:
        self.assertEqual([int(cable["cut_length"]) for cable in self.cables], [cable.length for cable in self.drawn])

    def test_each_cable_is_stripped_as_drawn(self) -> None:
        for drawn, cable in zip(self.drawn, self.cables):
            with self.subTest(cable["cable"]):
                self.assertEqual(drawn.strips, ["Strip 2.5mm", "Strip 30mm", "Strip 30mm", "Strip 4mm"])
                self.assertEqual((cable["strip_a"], cable["strip_b"]), ("30", "30"))
                rows = [row for row in self.wires if row["cable"] == cable["cable"]]
                self.assertEqual({(row["strip_a"], row["strip_b"]) for row in rows}, {("4", "2.5")})

    def test_each_conductor_runs_between_the_pins_drawn_in_its_colour(self) -> None:
        for drawn, cable in zip(self.drawn, self.cables):
            with self.subTest(cable["cable"]):
                built = {(row["from_pin"], row["to_pin"], row["color"]) for row in self.wires if row["cable"] == cable["cable"]}
                self.assertEqual(built, drawn.conductors)

    def test_the_drain_pins_in_the_notes_are_the_drawings(self) -> None:
        drains = [cable.drain_pin for cable in self.drawn]
        self.assertEqual(drains, ["5", "10", "15"])
        self.assertTrue(any(f"P1 PINS {drains[0]}, {drains[1]} AND {drains[2]}" in note for note in self.source["drawing"]["notes"]))

    def test_the_sleeving_is_as_drawn(self) -> None:
        self.assertEqual([cable.sleeving for cable in self.drawn], [cable.length - 20 for cable in self.drawn])
        [line] = [row for row in self.bom if row["pn"] == "EL-MS0073"]
        self.assertEqual(float(line["qty"]), sum(cable.sleeving for cable in self.drawn) / 1000)

    # The TAZ 6 drawing names parts by LulzBot part number; drawing EL-HR0143's parts list gives the
    # supplier part behind each. The example names the supplier part.
    def test_each_part_is_the_supplier_part_behind_the_drawings_part_number(self) -> None:
        import pypdf
        parts_list = " ".join(pypdf.PdfReader(lulzbot_parts_drawing).pages[1].extract_text().split())
        drawing_text = " ".join(text.text for text in self.texts)
        connectors, cables = self.source["connectors"], self.source["cables"]
        used = {"PC-CN0057": connectors["P1"]["pn"], "EL-MS0205": connectors["P1"]["contact"]["pn"],
                "EL-MS0355": connectors["J1"]["pn"], "EL-MS0351": connectors["J1"]["contact"]["pn"],
                "EL-WR0099": cables["W1"]["pn"]}
        for lulzbot_number, supplier_number in used.items():
            with self.subTest(lulzbot_number):
                self.assertIn(f"[{lulzbot_number}]", drawing_text)
                entry = re.search(re.escape(lulzbot_number) + r"(.*?)(?=\b(?:EL|PC|PP)-[A-Z]{2}\d{4}|$)", parts_list, re.I)[1]
                self.assertIn(supplier_number.replace(" ", ""), entry.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
