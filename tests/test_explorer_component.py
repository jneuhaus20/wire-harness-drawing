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


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class ExplorerComponentTest(unittest.TestCase):
    def test_the_component_passes_its_javascript_tests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "harness.yaml"
            source.write_text(routed_harness)
            routed_model = json.dumps(harness_model(analyse(load_source(source))))
        process = subprocess.run(["node", "--test", str(repository / "tests" / "explorer.test.mjs")], capture_output=True,
                                 text=True, env={"ROUTED_MODEL": routed_model, "PATH": shutil.which("node").rsplit("/", 1)[0]})
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)


if __name__ == "__main__":
    unittest.main()
