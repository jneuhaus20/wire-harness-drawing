"""Run the explorer component's JavaScript tests with Node, on the example and on a routed harness."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.generator import repository, example_text
from tests.test_cables import split_cable_harness
from tests.test_geometry import routed_harness

from harness.explorer_model import harness_model  # noqa: E402  (tests.generator puts scripts/ on the path)
from harness.package import analyse
from harness.source import load_source


twisted_cable_harness = example_text("twist-and-cable")


# Two splices put at the same place on a routed harness: the one the explorer must stack.
stacked_splice_harness = """
drawing: {title: STACKED, number: T-9, rev: A}
connectors:
  P1: {type: KK 254, pn: A-1, pincount: 2}
  J1: {type: KK 254, pn: A-2, pincount: 2}
  J2: {type: KK 254, pn: A-3, pincount: 2}
  SP1: {type: splice, pn: S-1}
  SP2: {type: splice, pn: S-1}
wires:
  - {id: W1, from: "P1:1", to: SP1, gauge: 20 AWG, color: BK}
  - {id: W2, from: SP1, to: "J1:1", gauge: 24 AWG, color: BK}
  - {id: W3, from: SP1, to: "J2:1", gauge: 24 AWG, color: BK}
  - {id: W4, from: "P1:2", to: SP2, gauge: 20 AWG, color: RD}
  - {id: W5, from: SP2, to: "J1:2", gauge: 24 AWG, color: RD}
  - {id: W6, from: SP2, to: "J2:2", gauge: 24 AWG, color: RD}
layout:
  root: P1
  nodes: {P1: [0, 0], SP1: [200, 0], SP2: [200, 0], B1: [300, 0], J1: [500, 0], J2: [300, 150]}
  segments: [[P1, SP1, 200], [SP1, SP2, 0], [SP2, B1, 100], [B1, J1, 200], [B1, J2, 150]]
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
        models = {"ROUTED_MODEL": model_of(routed_harness), "TWISTED_MODEL": model_of(twisted_cable_harness),
                  "STACKED_MODEL": model_of(stacked_splice_harness), "SPLIT_MODEL": model_of(split_cable_harness)}
        process = subprocess.run(["node", "--test", str(repository / "tests" / "explorer.test.mjs")], capture_output=True,
                                 text=True, env={**models, "PATH": shutil.which("node").rsplit("/", 1)[0]})
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)


if __name__ == "__main__":
    unittest.main()
