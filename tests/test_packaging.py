"""The repository installs as a Claude Code plugin marketplace and releases as a Claude skill zip."""
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.generator import example_source, repository

sys.path.insert(0, str(repository / "tools"))
from build_release import frontmatter, upload_problems, uploadable_frontmatter_keys  # noqa: E402

skill_name = "wire-harness-drawing"
skill_directory = repository / "skills" / skill_name
build_script = repository / "tools" / "build_release.py"


def plugin_manifest() -> dict:
    return json.loads((repository / ".claude-plugin" / "plugin.json").read_text())


class PluginManifestTest(unittest.TestCase):
    def test_the_plugin_is_named_for_the_skill_and_versioned(self) -> None:
        manifest = plugin_manifest()
        self.assertEqual(manifest["name"], skill_name)
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(manifest["license"], "MIT")
        self.assertTrue(manifest["description"])

    def test_the_repository_is_a_marketplace_offering_itself(self) -> None:
        marketplace = json.loads((repository / ".claude-plugin" / "marketplace.json").read_text())
        self.assertTrue(marketplace["name"])
        self.assertTrue(marketplace["owner"]["name"])
        self.assertEqual([(entry["name"], entry["source"]) for entry in marketplace["plugins"]], [(skill_name, "./")])

    def test_the_licence_is_mit(self) -> None:
        self.assertIn("MIT License", (repository / "LICENSE").read_text())


class SkillDocumentForUploadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata = frontmatter((skill_directory / "SKILL.md").read_text())

    def test_the_frontmatter_uses_only_keys_claude_ai_accepts(self) -> None:
        self.assertLessEqual(set(self.metadata), uploadable_frontmatter_keys)

    def test_the_name_matches_the_folder(self) -> None:
        self.assertEqual(self.metadata["name"], skill_name)

    def test_the_description_fits_the_upload_limit(self) -> None:
        self.assertLessEqual(len(self.metadata["description"]), 200)

    def test_the_licence_is_declared(self) -> None:
        self.assertEqual(self.metadata["license"], "MIT")

    def test_the_build_refuses_what_claude_ai_would_refuse(self) -> None:
        document = '---\nname: other\ndescription: "' + "x" * 201 + '"\nversion: 1\n---\n'
        problems = " ".join(upload_problems(document))
        for expected in ("'version' is not accepted", "differs from the folder name", "201 characters"):
            self.assertIn(expected, problems)


class ReleaseZipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary_directory.name)
        cls.process = subprocess.run([sys.executable, str(build_script), "--output", str(cls.output)],
                                     capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def zip_path(self) -> Path:
        return self.output / f"{skill_name}-{plugin_manifest()['version']}.zip"

    def test_the_zip_is_named_for_the_skill_and_version(self) -> None:
        self.assertEqual(self.process.returncode, 0, self.process.stderr)
        self.assertTrue(self.zip_path().exists(), list(self.output.iterdir()))

    def test_the_skill_folder_is_the_zip_root(self) -> None:
        names = zipfile.ZipFile(self.zip_path()).namelist()
        self.assertEqual({name.split("/")[0] for name in names}, {skill_name})
        for required in ("SKILL.md", "LICENSE", "scripts/harnessgen.py", "scripts/harness/package.py"):
            self.assertIn(f"{skill_name}/{required}", names)
        self.assertFalse([name for name in names if "__pycache__" in name or name.endswith(".pyc")])

    def test_the_zipped_skill_generates_the_example(self) -> None:
        unpacked = Path(self.enterContext(tempfile.TemporaryDirectory()))
        zipfile.ZipFile(self.zip_path()).extractall(unpacked)
        generator = unpacked / skill_name / "scripts" / "harnessgen.py"
        process = subprocess.run([sys.executable, str(generator), str(example_source), "-o", str(unpacked / "out"),
                                  "--no-wireviz"], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_a_tag_that_differs_from_the_version_is_refused(self) -> None:
        process = subprocess.run([sys.executable, str(build_script), "--output", str(self.output), "--tag", "v0.0.0"],
                                 capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("v0.0.0", process.stderr)


if __name__ == "__main__":
    unittest.main()
