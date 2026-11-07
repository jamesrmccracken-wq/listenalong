"""Regression tests for bounded PDF parsing on untrusted uploads."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import extract


class PDFResourceLimitsTests(unittest.TestCase):
    def test_rejects_page_count_before_extracting_any_text(self):
        first_page = Mock()
        reader = SimpleNamespace(pages=[first_page] * 4)
        with patch.object(extract, "PdfReader", return_value=reader), patch.object(extract, "MAX_PDF_PAGES", 3):
            with self.assertRaisesRegex(ValueError, "too many pages"):
                extract.extract_pdf(Path("example.pdf"), "Example")
        first_page.extract_text.assert_not_called()

    def test_rejects_oversized_text_before_later_pages(self):
        first_page = Mock()
        first_page.extract_text.return_value = "123456789"
        later_page = Mock()
        later_page.extract_text.return_value = "abcdefghij"
        never_page = Mock()
        reader = SimpleNamespace(pages=[first_page, later_page, never_page])
        with patch.object(extract, "PdfReader", return_value=reader), patch.object(extract, "MAX_BOOK_CHARS", 15):
            with self.assertRaisesRegex(ValueError, "too much text"):
                extract.extract_pdf(Path("example.pdf"), "Example")
        never_page.extract_text.assert_not_called()

    def test_valid_pdf_text_still_creates_chapters(self):
        pages = [SimpleNamespace(extract_text=lambda: "First page."),
                 SimpleNamespace(extract_text=lambda: "Second page.")]
        with patch.object(extract, "PdfReader", return_value=SimpleNamespace(pages=pages)):
            chapters = extract.extract_pdf(Path("example.pdf"), "Example")
        self.assertTrue(chapters)
        self.assertIn("First page.", chapters[0].text)
        self.assertIn("Second page.", chapters[0].text)

    def test_scanned_pdf_still_rejected(self):
        pages = [SimpleNamespace(extract_text=lambda: None)]
        with patch.object(extract, "PdfReader", return_value=SimpleNamespace(pages=pages)):
            with self.assertRaisesRegex(ValueError, "No text could be extracted"):
                extract.extract_pdf(Path("scanned.pdf"), "Scanned")


if __name__ == "__main__":
    unittest.main()
