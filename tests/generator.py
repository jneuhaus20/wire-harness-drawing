"""Shared access to the generator under test."""
import os
import subprocess
import sys
from pathlib import Path

repository = Path(__file__).resolve().parent.parent
skill_directory = repository / "skills" / "wire-harness-drawing"
generator_script = skill_directory / "scripts" / "harnessgen.py"
examples_directory = repository / "examples"
example_names = sorted(path.name for path in examples_directory.iterdir() if (path / f"{path.name}.yaml").exists())
example_directory = examples_directory / "sensor-branch"
example_source = example_directory / "sensor-branch.yaml"


def example_text(name: str) -> str:
    """The source of one of the examples in examples/, which the site shows and the tests use."""
    return (examples_directory / name / f"{name}.yaml").read_text()

# The tests reach the generator's modules the way scripts/harnessgen.py does.
sys.path.insert(0, str(skill_directory / "scripts"))


# Run the generator the way a user does, as a subprocess, so the tests exercise the
# command line and the exit code along with the outputs.
def run_generator(source: Path, output_directory: Path, *options: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    """Run harnessgen.py on a harness source and return the finished process; env adds to the environment."""
    command = [sys.executable, str(generator_script), str(source), "-o", str(output_directory), *options]
    return subprocess.run(command, capture_output=True, text=True, env={**os.environ, **(env or {})})


def run_generator_on_text(source_text: str, output_directory: Path, *options: str,
                          env: dict | None = None) -> subprocess.CompletedProcess[str]:
    """Write a harness source into output_directory as harness.yaml and run the generator on it."""
    source = output_directory / "harness.yaml"
    source.write_text(source_text)
    return run_generator(source, output_directory, *options, env=env)
