import os
import tempfile
import unittest
from pathlib import Path

from resolve_digest.output import digest_output_directory


class OutputTests(unittest.TestCase):
    def test_uses_creation_year_and_filename_day_month(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Дайджест 11 09.docx"
            path.write_bytes(b"")
            expected_year = path.stat().st_birthtime if hasattr(path.stat(), "st_birthtime") else path.stat().st_ctime
            year = __import__("datetime").datetime.fromtimestamp(expected_year).year
            result = digest_output_directory(path)
            self.assertEqual(result, Path(f"Z:/Workspace/Дайджест на экраны/{year} year/09_Сентябрь/11 09"))

    def test_rejects_filename_without_day_month(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Дайджест.docx"
            path.write_bytes(b"")
            with self.assertRaises(ValueError):
                digest_output_directory(path)

    def test_accepts_underscore_separator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Daydzhest_11_09.docx"
            path.write_bytes(b"")
            result = digest_output_directory(path)
            self.assertEqual(result.parts[-2:], ("09_Сентябрь", "11 09"))
