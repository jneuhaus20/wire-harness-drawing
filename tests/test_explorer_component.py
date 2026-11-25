"""Run the explorer component's JavaScript tests with Node, on the example and on a routed harness."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.generator import repository
from tests.test_geometry import routed_harness

from harness.explorer_model import harness_model  # noqa: E402  (tests.generator puts scripts/ on the path)
from harness.package import analyse
from harness.source import load_source


twisted_cable_harness = """
drawing: {title: TWIST AND CABLE, number: T-7, rev: A}
connectors:
  P1: {type: KK 254, pn: A-1, pincount: 4}
  J1: {type: KK 254, pn: A-2, pincount: 4}
cables:
  C1: {desc: 2-conductor shielded, pn: C-2, conductors: 2, shield: true}
wires:
  - {id: W1, from: "P1:1", to: "J1:1", gauge: 24 AWG, color: WH, twist: T1}
  - {id: W2, from: "P1:2", to: "J1:2", gauge: 24 AWG, color: GN, twist: T1}
  - {id: W3, from: "P1:3", to: "J1:3", gauge: 24 AWG, color: RD, cable: C1}
  - {id: W4, from: "P1:4", to: "J1:4", gauge: 24 AWG, color: BK, cable: C1}
layout:
  root: P1
  segments: [[P1, J1, 400]]
"""


def model_of(source_text: str) -> str:
    """The harness model of a source, as JSON."""
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "harness.yaml"
        source.write_text(source_text)
        return json.dumps(harness_model(analyse(load_source(source))))


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class ExplorerComponentTest(unittest.TestCase):
    def test_the_component_passes_its_javascript_tests(self) -> None:
        models = {"ROUTED_MODEL": model_of(routed_harness), "TWISTED_MODEL": model_of(twisted_cable_harness)}
        process = subprocess.run(["node", "--test", str(repository / "tests" / "explorer.test.mjs")], capture_output=True,
                                 text=True, env={**models, "PATH": shutil.which("node").rsplit("/", 1)[0]})
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)


if __name__ == "__main__":
    unittest.main()
