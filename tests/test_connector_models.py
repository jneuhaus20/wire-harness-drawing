"""A connector's body can be its maker's 3D model: converted once, cached, and baked into the harness model.

The converter needs Node and occt-import-js. CI installs it and points WIRE_HARNESS_CONVERTER at it; without it
these tests are skipped, and the generator falls back to the datasheet body or a placeholder (tested below too).
"""
import base64
import json
import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from tests.generator import example_text, repository, run_generator_on_text

from harness.models import resolve_model_path  # noqa: E402  (tests.generator puts scripts/ on the path)

fixture_model = repository / "tests" / "fixtures" / "kicad" / "JST_PH_B6B-PH-K_1x06_P2.00mm_Vertical.step"
converter = os.environ.get("WIRE_HARNESS_CONVERTER", "")
converter_installed = bool(converter) and (Path(converter) / "node_modules" / "occt-import-js").exists() and bool(shutil.which("node"))


def harness_with_model(model: str, extra: str = "") -> str:
    """The two-wire harness with J1's body given as a model."""
    return example_text("two-wire").replace("J1: {type: KK 254,", f"J1: {{body: {{model: '{model}'{extra}}}, type: KK 254,")


class ModelPathTest(unittest.TestCase):
    def test_a_kicad_model_variable_resolves_to_an_installed_library(self) -> None:
        library = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (library / "Connector_JST.3dshapes").mkdir()
        (library / "Connector_JST.3dshapes" / "x.step").write_text("")
        path = resolve_model_path("${KICAD10_3DMODEL_DIR}/Connector_JST.3dshapes/x.step", Path("/"), {"KICAD10_3DMODEL_DIR": str(library)})
        self.assertEqual(path, library / "Connector_JST.3dshapes" / "x.step")

    def test_a_relative_model_path_is_read_from_the_source_folder(self) -> None:
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (folder / "part.step").write_text("")
        self.assertEqual(resolve_model_path("part.step", folder, {}), folder / "part.step")

    def test_a_missing_model_resolves_to_nothing(self) -> None:
        self.assertIsNone(resolve_model_path("${KICAD10_3DMODEL_DIR}/nope.step", Path("/"), {}))


class ModelFallbackTest(unittest.TestCase):
    def generate(self, source: str, environment: dict) -> tuple[str, dict]:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        cache = Path(self.enterContext(tempfile.TemporaryDirectory()))
        process = run_generator_on_text(source, directory, "--no-wireviz", env={"WIRE_HARNESS_CACHE": str(cache), **environment})
        self.assertNotIn("Traceback", process.stderr, process.stderr)
        model = json.loads((directory / "harness.harness.json").read_text())
        return (directory / "harness.checks.txt").read_text(), next(c for c in model["connectors"] if c["id"] == "J1")

    def test_a_model_that_cannot_be_found_is_reported_and_the_body_is_not_stated(self) -> None:
        checks, j1 = self.generate(harness_with_model("missing.step"), {})
        self.assertIn("WARN   J1: body model missing.step not found; drawn as a placeholder", checks)
        self.assertIsNone(j1["body"])

    def test_without_the_converter_the_datasheet_body_is_kept(self) -> None:
        source = harness_with_model(str(fixture_model), ", shape: box, length: 6, width: 13.9, height: 4.5, color: natural")
        checks, j1 = self.generate(source, {"WIRE_HARNESS_CONVERTER": "/nonexistent"})
        self.assertIn("J1: body model not converted: occt-import-js is not installed", checks)
        self.assertEqual((j1["body"]["shape"], j1["body"].get("mesh")), ("box", None))


class ConvertedMeshTest(unittest.TestCase):
    # A mesh already converted (the converter's own output) is read as it is, with no converter: so
    # an example can carry its connectors' meshes and build anywhere.
    def test_a_body_can_name_a_converted_mesh(self) -> None:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shutil.copy(repository / "tests" / "fixtures" / "ph-mesh.json", directory / "ph.mesh.json")
        source = harness_with_model("ph.mesh.json", ", rotate: [0, 90, 0]")
        process = run_generator_on_text(source, directory, "--no-wireviz", env={"WIRE_HARNESS_CONVERTER": "/nonexistent"})
        self.assertNotIn("Traceback", process.stderr, process.stderr)
        model = json.loads((directory / "harness.harness.json").read_text())
        j1 = next(c for c in model["connectors"] if c["id"] == "J1")
        self.assertEqual(j1["body"]["mesh"]["triangles"], json.loads((directory / "ph.mesh.json").read_text())["triangles"])
        self.assertEqual(j1["body"]["rotate"], [0, 90, 0])
        self.assertNotIn("body model", (directory / "harness.checks.txt").read_text())


@unittest.skipUnless(converter_installed, "set WIRE_HARNESS_CONVERTER to a folder with occt-import-js installed")
class ModelMeshTest(unittest.TestCase):
    def generate(self, source: str, cache: Path) -> tuple[str, dict]:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        process = run_generator_on_text(source, directory, "--no-wireviz", env={"WIRE_HARNESS_CACHE": str(cache)})
        self.assertNotIn("Traceback", process.stderr, process.stderr)
        model = json.loads((directory / "harness.harness.json").read_text())
        return (directory / "harness.checks.txt").read_text(), next(c for c in model["connectors"] if c["id"] == "J1")

    def test_the_model_is_baked_into_the_harness_model_at_its_true_size(self) -> None:
        cache = Path(self.enterContext(tempfile.TemporaryDirectory()))
        checks, j1 = self.generate(harness_with_model(str(fixture_model)), cache)
        self.assertNotIn("body model", checks)
        mesh = j1["body"]["mesh"]
        self.assertLessEqual(mesh["triangles"], 8000)
        extent = [round(high - low, 2) for low, high in zip(mesh["min"], mesh["max"])]
        self.assertEqual(extent[0], 13.9, "B6B-PH-K is 13.9 mm wide across its contacts")
        positions = base64.b64decode(mesh["positions"])
        self.assertEqual(len(positions), 2 * 3 * len(struct.unpack(f"<{len(positions) // 2}H", positions)) // 3)
        self.assertEqual(len(base64.b64decode(mesh["triangle_colors"])), mesh["triangles"])

    def test_a_converted_model_is_cached_and_reused(self) -> None:
        cache = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.generate(harness_with_model(str(fixture_model)), cache)
        [cached] = (cache / "meshes").glob("*.json")
        cached.write_text(cached.read_text().replace('"triangles":', '"from_cache": true, "triangles":'))
        _, j1 = self.generate(harness_with_model(str(fixture_model)), cache)
        self.assertTrue(j1["body"]["mesh"].get("from_cache"))

    def test_a_model_in_the_cache_is_found_by_part_number(self) -> None:
        cache = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (cache / "models").mkdir()
        shutil.copy(fixture_model, cache / "models" / "22-01-3027.step")
        source = example_text("two-wire").replace("J1: {type: KK 254,", "J1: {pn: 22-01-3027, type: KK 254,")
        _, j1 = self.generate(source, cache)
        self.assertIn("mesh", j1["body"])


if __name__ == "__main__":
    unittest.main()
