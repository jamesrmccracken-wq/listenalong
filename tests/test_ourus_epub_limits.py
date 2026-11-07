"""Regression tests for cumulative EPUB extraction limits."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import zipfile

import extract


class EPUBResourceLimitsTests(unittest.TestCase):
    def test_aggregate_text_rejected_during_chapter_extraction(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "large.epub"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("chapter1.xhtml", "<p>" + "a" * 60 + "</p>")
                zf.writestr("chapter2.xhtml", "<p>" + "b" * 60 + "</p>")
            with patch.object(extract, "MAX_BOOK_CHARS", 100):
                with self.assertRaisesRegex(ValueError, "too large to narrate"):
                    extract.extract_epub(path, "Large")

    def test_small_epub_still_extracts(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "small.epub"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("chapter.xhtml", "<p>" + "Readable content " * 4 + "</p>")
            chapters = extract.extract_epub(path, "Small")
            self.assertTrue(chapters)
            self.assertIn("Readable content", chapters[0].text)


if __name__ == "__main__":
    unittest.main()
