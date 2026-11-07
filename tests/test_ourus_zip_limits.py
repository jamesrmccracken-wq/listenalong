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



class DocumentContainerLimitsTests(unittest.TestCase):
    def test_docx_is_validated_before_mammoth(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / 'large.docx'
            with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('word/document.xml', 'x' * 100)
            with patch.object(extract, 'MAX_ZIP_UNCOMPRESSED_BYTES', 50), patch.object(extract.mammoth, 'extract_raw_text') as parser:
                with self.assertRaisesRegex(ValueError, 'too much uncompressed data'):
                    extract.extract_docx(archive, 'Large')
                parser.assert_not_called()

    def test_epub_rejects_oversized_member_before_xml_parse(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / 'large.epub'
            with zipfile.ZipFile(archive, 'w') as zf:
                zf.writestr('book.opf', 'not xml' * 10)
            with patch.object(extract, 'MAX_FILE_BYTES', 20), patch.object(extract.ET, 'fromstring') as parser:
                with self.assertRaisesRegex(ValueError, 'oversized member'):
                    extract.extract_epub(archive, 'Large')
                parser.assert_not_called()

    def test_container_entry_limit_includes_non_document_members(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / 'many.epub'
            with zipfile.ZipFile(archive, 'w') as zf:
                for index in range(4):
                    zf.writestr(f'image-{index}.png', 'small')
            with patch.object(extract, 'MAX_ZIP_ENTRIES', 3):
                with self.assertRaisesRegex(ValueError, 'too many documents'):
                    extract.extract_epub(archive, 'Many')

    def test_valid_epub_still_extracts(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / 'small.epub'
            with zipfile.ZipFile(archive, 'w') as zf:
                zf.writestr('chapter.xhtml', '<html><body><p>Readable chapter. This is enough ordinary text to pass the existing chapter minimum length.</p></body></html>')
            chapters = extract.extract_epub(archive, 'Small')
            self.assertTrue(any('Readable chapter.' in ch.text for ch in chapters))

if __name__ == "__main__":
    unittest.main()
