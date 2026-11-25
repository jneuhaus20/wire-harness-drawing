"""The project site shows every example and only examples, built from their sources by the same generator."""
import html
import json
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.generator import example_names, repository, skill_directory

site_source = repository / "site"
build_script = repository / "tools" / "build_site.py"


def bound_value(site: Path, binding: str) -> object:
    """The value a binding such as split-cable.cables.W5.cut_length names in its example's built model."""
    name, *path = binding.split(".")
    value = json.loads((site / "examples" / name / f"{name}.harness.json").read_text())
    for key in path:
        if isinstance(value, list):
            value = value[int(key)] if key.isdigit() else next(item for item in value if item.get("id") == key)
        else:
            value = value[key]
    return value


class SiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary_directory.name) / "_site"
        cls.process = subprocess.run([sys.executable, str(build_script), "--output", str(cls.output), "--no-wireviz"],
                                     capture_output=True, text=True)
        cls.page = (cls.output / "index.html").read_text() if (cls.output / "index.html").exists() else ""

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_the_site_builds(self) -> None:
        self.assertEqual(self.process.returncode, 0, self.process.stdout + self.process.stderr)

    def test_every_example_is_shown_and_every_demo_is_an_example(self) -> None:
        shown = set(re.findall(r'data-example="([^"]+)"', self.page))
        self.assertEqual(shown, set(example_names))

    def test_each_example_is_built_from_its_source(self) -> None:
        for name in example_names:
            folder = self.output / "examples" / name
            with self.subTest(name):
                for file in (f"{name}.yaml", f"{name}.harness.json", f"{name}.sheet1.svg", f"{name}.sheet2.svg", f"{name}.checks.txt"):
                    self.assertTrue((folder / file).exists(), file)
                built = json.loads((folder / f"{name}.harness.json").read_text())
                committed = json.loads((repository / "examples" / name / f"{name}.harness.json").read_text())
                self.assertEqual(built, committed)

    def test_the_site_serves_the_skills_own_component(self) -> None:
        served = (self.output / "wire-harness-explorer.js").read_bytes()
        self.assertEqual(served, (skill_directory / "explorer" / "wire-harness-explorer.js").read_bytes())

    def test_every_local_link_and_asset_exists(self) -> None:
        for reference in re.findall(r'(?:href|src)="([^"#:]+)"', self.page):
            with self.subTest(reference):
                self.assertTrue((self.output / reference).exists(), reference)

    # Numbers in the page's prose are bound to an example's model, never typed in.
    def test_every_bound_number_resolves_in_its_model(self) -> None:
        bindings = re.findall(r'data-bind="([^"]+)"', self.page)
        self.assertTrue(bindings)
        for binding in bindings:
            with self.subTest(binding):
                self.assertIsInstance(bound_value(self.output, binding), (str, int, float))

    def test_each_bound_number_is_written_into_the_page(self) -> None:
        for binding, shown in re.findall(r'data-bind="([^"]+)">([^<]*)<', self.page):
            with self.subTest(binding):
                self.assertEqual(shown, str(bound_value(self.output, binding)))

    def test_each_included_file_is_written_into_the_page_as_built(self) -> None:
        includes = re.findall(r'data-include="([^"]+)">(.*?)</pre>', self.page, re.S)
        self.assertTrue(includes)
        for path, shown in includes:
            with self.subTest(path):
                self.assertEqual(html.unescape(shown), (self.output / path).read_text())

    def test_each_explorer_carries_its_examples_model(self) -> None:
        explorers = re.findall(r'<wire-harness-explorer[^>]*data-model="([^"]+)"[^>]*>\s*<script type="application/json">(.*?)</script>',
                               self.page, re.S)
        self.assertTrue(explorers)
        self.assertEqual(len(explorers), self.page.count("<wire-harness-explorer"))
        for name, model in explorers:
            with self.subTest(name):
                self.assertEqual(json.loads(model), json.loads((self.output / "examples" / name / f"{name}.harness.json").read_text()))

    def test_the_release_zip_carries_no_site_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, str(repository / "tools" / "build_release.py"), "--output", directory], check=True,
                           capture_output=True)
            names = zipfile.ZipFile(next(Path(directory).glob("*.zip"))).namelist()
        self.assertFalse([name for name in names if "/site/" in name or name.endswith("index.html")])


if __name__ == "__main__":
    unittest.main()
