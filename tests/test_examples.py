"""Every example in examples/ is under test: its committed outputs are what the generator makes from its source."""
import tempfile
import unittest
from pathlib import Path

from tests.generator import examples_directory, example_names, repository, run_generator

golden_directory = repository / "tests" / "golden"
# The text outputs committed beside each example's source; cables.csv only where it has a cable.
committed_outputs = ("checks.txt", "bom.csv", "wirelist.csv", "cables.csv", "harness.json")


class ExamplesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.runs = {}
        for name in example_names:
            output = Path(cls.temporary_directory.name) / name
            # The WireViz sheet depends on the installed Graphviz, so the pinned runs leave it out.
            cls.runs[name] = (output, run_generator(examples_directory / name / f"{name}.yaml", output, "--no-wireviz"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_there_are_examples(self) -> None:
        self.assertIn("sensor-branch", example_names)
        self.assertGreaterEqual(len(example_names), 7)

    def test_an_example_exits_1_exactly_when_its_checks_report_an_error(self) -> None:
        for name, (output, process) in self.runs.items():
            with self.subTest(name):
                self.assertNotIn("Traceback", process.stderr)
                failed = "ERROR" in (output / f"{name}.checks.txt").read_text()
                self.assertEqual(process.returncode, 1 if failed else 0, process.stdout)

    def test_committed_outputs_match_the_generator(self) -> None:
        for name, (output, _) in self.runs.items():
            for suffix in committed_outputs:
                generated, committed = output / f"{name}.{suffix}", examples_directory / name / f"{name}.{suffix}"
                with self.subTest(f"{name}.{suffix}"):
                    self.assertEqual(generated.exists(), committed.exists(), f"{committed} is missing or extra")
                    if generated.exists():
                        self.assertEqual(generated.read_text(), committed.read_text(), f"{committed} is stale")

    def test_sheets_match_their_goldens(self) -> None:
        for name, (output, _) in self.runs.items():
            for sheet in ("sheet1", "sheet2"):
                with self.subTest(f"{name}.{sheet}"):
                    self.assertEqual((output / f"{name}.{sheet}.svg").read_text(),
                                     (golden_directory / f"{name}.{sheet}.svg").read_text())

    def test_the_flagship_example_passes_its_checks(self) -> None:
        self.assertEqual(self.runs["sensor-branch"][1].returncode, 0)


class WiringDiagramSourceTest(unittest.TestCase):
    def test_the_flagship_wireviz_source_matches_the_golden(self) -> None:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        process = run_generator(examples_directory / "sensor-branch" / "sensor-branch.yaml", directory)
        if "wireviz or graphviz" in process.stdout:
            self.skipTest("WireViz or Graphviz is not installed")
        generated = (directory / "sensor-branch.wireviz.yaml").read_text()
        self.assertEqual(generated, (golden_directory / "sensor-branch.wireviz.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
