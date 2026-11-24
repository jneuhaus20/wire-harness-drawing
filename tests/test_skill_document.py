"""SKILL.md points at the one generator script instead of carrying a second copy."""
import re
import unittest

from tests.generator import generator_script, skill_directory

skill_document = (skill_directory / "SKILL.md").read_text()


class SkillDocumentTest(unittest.TestCase):
    def test_document_carries_no_copy_of_the_generator(self) -> None:
        self.assertFalse("def main()" in skill_document, "SKILL.md defines the generator's main()")
        self.assertFalse("```python" in skill_document, "SKILL.md embeds Python source")

    def test_every_generator_command_names_the_script_in_the_skill(self) -> None:
        commands = re.findall(r"python3 (\S*harnessgen\.py)", skill_document)
        self.assertTrue(commands, "SKILL.md shows no generator command")
        for script_path in commands:
            self.assertTrue(script_path.endswith("scripts/harnessgen.py"), script_path)
        self.assertTrue(generator_script.exists())


if __name__ == "__main__":
    unittest.main()
