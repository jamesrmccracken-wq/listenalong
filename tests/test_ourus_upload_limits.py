"""Actual import route/helper with bounded uploads and mocked extraction."""
import ast
from io import BytesIO
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import File, Form, HTTPException, UploadFile

SOURCE = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text())
NAMES = {'read_upload_bounded', 'create_book'}
FUNCTIONS = [n for n in SOURCE.body if isinstance(n, ast.AsyncFunctionDef) and n.name in NAMES]
assert {n.name for n in FUNCTIONS} == NAMES


class UploadLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = Mock()
        self.extractor = SimpleNamespace(
            MAX_FILE_BYTES=10, MAX_BOOK_CHARS=10,
            is_supported=lambda name: True,
            title_from_name=lambda name: name,
            extract_bytes=Mock(return_value=[SimpleNamespace(title='Chapter', text='123456')]))
        self.ns = dict(
            app=SimpleNamespace(post=lambda *args: lambda fn: fn),
            File=File, Form=Form, UploadFile=UploadFile, DEFAULT_VOICE='test',
            HTTPException=HTTPException, extract=self.extractor, UPLOADS=Path(self.tmp.name),
            Path=Path, os=os, shutil=shutil, MAX_IMPORT_FILES=3, MAX_IMPORT_BYTES=15,
            db=self.database)
        exec(compile(ast.Module(body=FUNCTIONS, type_ignores=[]), 'app.py:import-route', 'exec'), self.ns)

    def upload(self, body, name='note.txt'):
        return UploadFile(filename=name, file=BytesIO(body))

    async def import_files(self, files):
        return await self.ns['create_book'](files, '', '', 'test')

    async def test_exact_per_file_limit_is_accepted(self):
        body = await self.ns['read_upload_bounded'](self.upload(b'a' * 10), 15)
        self.assertEqual(len(body), 10)

    async def test_oversized_upload_read_is_bounded(self):
        upload = self.upload(b'a' * 100)
        upload.read = AsyncMock(wraps=upload.read)
        with self.assertRaises(HTTPException) as caught:
            await self.ns['read_upload_bounded'](upload, 15)
        self.assertEqual(caught.exception.status_code, 413)
        upload.read.assert_awaited_once_with(11)
        self.assertEqual(upload.file.tell(), 11)

    async def test_remaining_request_budget_limits_read(self):
        upload = self.upload(b'a' * 10)
        upload.read = AsyncMock(wraps=upload.read)
        with self.assertRaises(HTTPException):
            await self.ns['read_upload_bounded'](upload, 4)
        upload.read.assert_awaited_once_with(5)

    async def test_file_count_rejected_before_reads_and_work_directory(self):
        files = [self.upload(b'x') for _ in range(4)]
        with self.assertRaises(HTTPException) as caught:
            await self.import_files(files)
        self.assertEqual(caught.exception.status_code, 413)
        self.assertTrue(all(f.file.tell() == 0 for f in files))
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        self.database.execute.assert_not_called()

    async def test_multiple_files_cannot_exceed_total_bytes(self):
        files = [self.upload(b'a' * 8), self.upload(b'b' * 8)]
        with self.assertRaises(HTTPException) as caught:
            await self.import_files(files)
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(self.extractor.extract_bytes.call_count, 1)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        self.database.execute.assert_not_called()

    async def test_multiple_files_cannot_exceed_total_text(self):
        files = [self.upload(b'a'), self.upload(b'b')]
        with self.assertRaises(HTTPException) as caught:
            await self.import_files(files)
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(self.extractor.extract_bytes.call_count, 2)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        self.database.execute.assert_not_called()

    async def test_single_file_limit_precedes_extraction(self):
        with self.assertRaises(HTTPException) as caught:
            await self.import_files([self.upload(b'a' * 11)])
        self.assertEqual(caught.exception.status_code, 413)
        self.extractor.extract_bytes.assert_not_called()
        self.database.execute.assert_not_called()
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
