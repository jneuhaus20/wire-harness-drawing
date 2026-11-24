"""Shared access to the generator under test."""
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

repository = Path(__file__).resolve().parent.parent
generator_script = repository / "scripts" / "harnessgen.py"
example_directory = repository / "example"
example_source = example_directory / "example.yaml"


# Run the generator the way a user does, as a subprocess, so the tests exercise the
# command line and the exit code along with the outputs.
def run_generator(source: Path, output_directory: Path, *options: str) -> subprocess.CompletedProcess[str]:
    """Run harnessgen.py on a harness source and return the finished process."""
    command = [sys.executable, str(generator_script), str(source), "-o", str(output_directory), *options]
    return subprocess.run(command, capture_output=True, text=True)


def run_generator_on_text(source_text: str, output_directory: Path, *options: str) -> subprocess.CompletedProcess[str]:
    """Write a harness source into output_directory as harness.yaml and run the generator on it."""
    source = output_directory / "harness.yaml"
    source.write_text(source_text)
    return run_generator(source, output_directory, *options)


# Import the script as a module so tests can reach the functions behind the command line.
def load_generator_module() -> ModuleType:
    """Import scripts/harnessgen.py and return it as a module."""
    specification = importlib.util.spec_from_file_location("harnessgen", generator_script)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module
