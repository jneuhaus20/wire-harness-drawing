"""A connector's body is drawn at the size, shape and colour its datasheet gives, when the source states them."""
import tempfile
import unittest
from pathlib import Path

from tests.generator import example_text, run_generator_on_text

from harness.explorer_model import harness_model  # noqa: E402  (tests.generator puts scripts/ on the path)
from harness.package import analyse
from harness.source import load_source


def model_of(text: str) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "harness.yaml"
        path.write_text(text)
        return harness_model(analyse(load_source(path)))


class ConnectorBodyTest(unittest.TestCase):
    def test_a_stated_body_reaches_the_explorer_with_its_colour_resolved(self) -> None:
        source = example_text("two-wire").replace("J1: {type: KK 254,", "J1: {body: {shape: box, length: 6.35, width: 13.8, height: 4.5, color: natural}, type: KK 254,")
        j1 = next(connector for connector in model_of(source)["connectors"] if connector["id"] == "J1")
        self.assertEqual(j1["body"], {"shape": "box", "length": 6.35, "width": 13.8, "height": 4.5, "color": "#ece6d6"})

    def test_a_body_not_stated_is_marked_so(self) -> None:
        p1 = next(connector for connector in model_of(example_text("two-wire"))["connectors"] if connector["id"] == "P1")
        self.assertIsNone(p1["body"])

    def test_a_body_of_the_wrong_kind_is_reported(self) -> None:
        source = example_text("two-wire").replace("J1: {type: KK 254,", "J1: {body: {shape: blob, length: -1, color: plaid}, type: KK 254,")
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        run_generator_on_text(source, directory, "--check-only")
        findings = (directory / "harness.checks.txt").read_text()
        self.assertIn("ERROR  J1: body shape 'blob' is not box, cylinder or dsub", findings)
        self.assertIn("ERROR  J1: body length must be a number above 0", findings)
        self.assertIn("ERROR  J1: body colour 'plaid' is not a colour name or #rrggbb", findings)


if __name__ == "__main__":
    unittest.main()
