"""The committed example outputs are what the generator produces from example.yaml."""
import tempfile
import unittest
from pathlib import Path

from tests.generator import example_directory, example_source, repository, run_generator

golden_directory = repository / "tests" / "golden"


class ExamplePackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.output_directory = Path(cls.temporary_directory.name)
        # The WireViz sheet depends on the installed Graphviz, so the pinned run leaves it out.
        cls.process = run_generator(example_source, cls.output_directory, "--no-wireviz")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def assert_same_text(self, generated_name: str, committed: Path) -> None:
        generated = (self.output_directory / generated_name).read_text()
        self.assertEqual(generated, committed.read_text(), f"{generated_name} differs from {committed}")

    def test_exit_code_reports_the_examples_deliberate_errors(self) -> None:
        self.assertEqual(self.process.returncode, 1, self.process.stderr)

    def test_checks_match_the_committed_example(self) -> None:
        self.assert_same_text("example.checks.txt", example_directory / "example.checks.txt")

    def test_bill_of_materials_matches_the_committed_example(self) -> None:
        self.assert_same_text("example.bom.csv", example_directory / "example.bom.csv")

    def test_wire_list_matches_the_committed_example(self) -> None:
        self.assert_same_text("example.wirelist.csv", example_directory / "example.wirelist.csv")

    def test_harness_drawing_sheet_matches_the_golden(self) -> None:
        self.assert_same_text("example.sheet1.svg", golden_directory / "example.sheet1.svg")

    def test_table_sheet_matches_the_golden(self) -> None:
        self.assert_same_text("example.sheet2.svg", golden_directory / "example.sheet2.svg")


if __name__ == "__main__":
    unittest.main()
