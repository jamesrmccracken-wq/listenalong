"""Regression tests for ZIP extraction resource limits."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import zipfile

import extract


class ZipResourceLimitsTests(unittest.TestCase):
    def test_rejects_too_many_documents(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "many.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                for index in range(extract.MAX_ZIP_ENTRIES + 1):
                    zf.writestr(f"note-{index}.txt", "small")
            with self.assertRaisesRegex(ValueError, "too many documents"):
                extract.extract_zip(archive, "Many")

    def test_rejects_large_total_uncompressed_size(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "large.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("first.txt", "small")
                zf.writestr("second.txt", "small")
            with patch.object(extract, "MAX_ZIP_UNCOMPRESSED_BYTES", 5):
                with self.assertRaisesRegex(ValueError, "too much uncompressed data"):
                    extract.extract_zip(archive, "Large")


    def test_rejects_aggregate_text_across_multiple_files(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "aggregate.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("first.txt", "abcdefghij")
                zf.writestr("second.txt", "klmnopqrst")
            with patch.object(extract, "MAX_BOOK_CHARS", 15):
                with self.assertRaisesRegex(ValueError, "too large to narrate"):
                    extract.extract_zip(archive, "Aggregate")

if __name__ == "__main__":
    unittest.main()
