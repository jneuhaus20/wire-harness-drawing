"""Connector 3D models: where a model file is, its mesh converted once and cached, baked into the source."""
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from harness.source import Findings, HarnessSource

converter_script = Path(__file__).resolve().parent.parent / "model_mesh.mjs"
model_suffixes = (".step", ".stp", ".iges", ".igs")
max_triangles = 8000

# Where KiCad installs its 3D model library, by platform; the newest version found is used for
# any KICADn_3DMODEL_DIR the environment does not set.
kicad_model_directories = [
    Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels"),
    Path("/usr/share/kicad/3dmodels"),
    Path("/usr/local/share/kicad/3dmodels"),
    *sorted(Path("C:/Program Files/KiCad").glob("*/share/kicad/3dmodels"), reverse=True),
]


def cache_directory() -> Path:
    """The skill's own store of downloaded models and converted meshes."""
    return Path(os.environ.get("WIRE_HARNESS_CACHE") or Path.home() / ".cache" / "wire-harness-drawing")


def converter_directory() -> Path:
    """Where occt-import-js is installed for the converter."""
    return Path(os.environ.get("WIRE_HARNESS_CONVERTER") or cache_directory() / "converter")


# ${VARIABLES} come from the environment, and a KiCad model variable not set there from the
# installed KiCad. A relative path is read from the folder the harness source is in.
def resolve_model_path(text: str, folder: Path, environment: dict) -> Path | None:
    """The model file a body's model names, or None if it does not exist."""
    def variable(match: re.Match) -> str:
        name = match[1]
        if name in environment:
            return environment[name]
        if re.fullmatch(r"KICAD\d*_3DMODEL_DIR", name):
            installed = next((directory for directory in kicad_model_directories if directory.is_dir()), None)
            return str(installed) if installed else match[0]
        return match[0]

    expanded = Path(os.path.expanduser(re.sub(r"\$\{(\w+)\}", variable, str(text))))
    path = expanded if expanded.is_absolute() else folder / expanded
    return path if path.is_file() else None


def cached_model_for(part_number: str) -> Path | None:
    """A model the cache holds for a part number, as models/<part number>.step (or .stp, .iges, .igs)."""
    if not part_number:
        return None
    name = re.sub(r"[^\w.-]", "_", str(part_number))
    return next((path for suffix in model_suffixes if (path := cache_directory() / "models" / f"{name}{suffix}").is_file()), None)


# A model is converted once: its mesh is kept in the cache under a hash of the model file and the
# triangle cap, so every harness that uses the part reuses it.
def converted_mesh(path: Path) -> tuple[dict | None, str | None]:
    """The model's mesh, from the cache or freshly converted; or None and why not."""
    import json
    key = hashlib.sha256(path.read_bytes() + str(max_triangles).encode()).hexdigest()[:24]
    cached = cache_directory() / "meshes" / f"{key}.json"
    if cached.is_file():
        return json.loads(cached.read_text()), None
    if not shutil.which("node"):
        return None, "Node.js is not installed"
    if not (converter_directory() / "node_modules" / "occt-import-js").is_dir():
        return None, f"occt-import-js is not installed in {converter_directory()}"
    cached.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(["node", str(converter_script), str(path), str(cached), "--max-triangles", str(max_triangles),
                              "--converter", str(converter_directory())], capture_output=True, text=True)
    if process.returncode != 0 or not cached.is_file():
        return None, (process.stderr.strip().splitlines() or ["the converter failed"])[-1]
    return json.loads(cached.read_text()), None


# A mesh the converter has already written (its .json) is read as it is, so a harness can carry
# its connectors' meshes beside its source and build where no converter is installed.
def read_mesh(path: Path) -> tuple[dict | None, str | None]:
    """A converted mesh file, or None and why not."""
    import json
    try:
        mesh = json.loads(path.read_text())
    except ValueError:
        return None, f"{path.name} is not a mesh file"
    if mesh.get("format") != "wire-harness-mesh/1":
        return None, f"{path.name} is not a wire-harness-mesh/1 file"
    return mesh, None


# A body's model is the file it names, or else a model the cache holds for the connector's part
# number. Its mesh joins the body; a model that cannot be found or converted leaves the body as
# its datasheet states it, or a placeholder when it states nothing else.
def attach_models(source: HarnessSource, findings: Findings) -> None:
    """Give each connector body with a model its mesh."""
    folder = Path(source.get("_folder", "."))
    for designator, connector in source["connectors"].items():
        body = dict(connector.get("body") or {})
        named = body.pop("model", None)
        path = resolve_model_path(named, folder, dict(os.environ)) if named else cached_model_for(connector.get("pn"))
        fallback = "drawn from its datasheet body" if "shape" in body else "drawn as a placeholder"
        if named and path is None:
            findings.warn(f"{designator}: body model {named} not found; {fallback}")
        mesh, problem = (read_mesh(path) if path.suffix.lower() == ".json" else converted_mesh(path)) if path else (None, None)
        if problem:
            findings.info(f"{designator}: body model not converted: {problem}; {fallback}")
        if mesh:
            body["mesh"] = mesh
        if "shape" in body or "mesh" in body:
            connector["body"] = body
        else:
            connector.pop("body", None)


if __name__ == "__main__":
    sys.exit("This module is part of harnessgen.py.")
