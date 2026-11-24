"""Shared access to the generator under test."""
import subprocess
import sys
from pathlib import Path

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
