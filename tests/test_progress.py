import io
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from resolve_digest.progress import WindowsProgress, ProgressCancelled
from resolve_digest.article_images import download_all_article_images
from resolve_digest.models import Article
from resolve_digest import fusion
from test_startup import launcher
from test_fusion import Composition


class ProgressTests(unittest.TestCase):
    def controller(self):
        progress = WindowsProgress.__new__(WindowsProgress)
        progress._cancelled = threading.Event()
        progress._finished = False
        progress._percent = 0
        progress._process = MagicMock()
        progress._process.poll.return_value = None
        progress._process.stdin = io.StringIO()
        return progress

    def test_cancel_prevents_next_update(self):
        progress = self.controller()
        progress._cancelled.set()
        with self.assertRaises(ProgressCancelled):
            progress.update(40, 'Downloading')
        self.assertEqual(progress._process.stdin.getvalue(), '')

    def test_progress_does_not_go_backwards_or_finish_early(self):
        import json
        progress = self.controller()
        progress.update(46, 'Новость 3/5', 'Фото 2/6')
        progress.update(20, 'Next')
        progress.update(100, 'Almost')
        states = [json.loads(line) for line in progress._process.stdin.getvalue().splitlines()]
        self.assertEqual([state['percent'] for state in states], [46, 46, 99])
        self.assertEqual(states[0]['message'], 'Новость 3/5')

    def test_closed_window_is_an_error(self):
        progress = self.controller()
        progress._diagnostics = ['unexpected exit']
        progress._process.poll.return_value = 1
        with self.assertRaisesRegex(RuntimeError, 'unexpected exit'):
            progress.check_cancelled()

    def test_callback_can_cancel_before_directory_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / 'photo_01.jpg'
            existing.write_bytes(b'keep')
            def cancel(*args):
                raise ProgressCancelled()
            with patch('resolve_digest.article_images.article_image_urls') as extract:
                with self.assertRaises(ProgressCancelled):
                    download_all_article_images('https://example.test', Path(directory), on_progress=cancel)
                extract.assert_not_called()
            self.assertEqual(existing.read_bytes(), b'keep')

    @unittest.skipUnless(os.name == 'nt', 'Real WinForms protocol')
    def test_real_window_acknowledges_error_then_success_state(self):
        # No Resolve API or network is used. Dispose this test's child process.
        for status in ('error', 'success', 'cancelled'):
            with self.subTest(status=status):
                progress = WindowsProgress()
                try:
                    progress.update(40, 'Тест прогресса', 'Тест без изменения проекта')
                    progress.finish(status, 'Проверка итога', 'Подробности сообщения')
                    self.assertTrue(progress._terminal_received.is_set())
                finally:
                    progress._stop()


class ProgressWorkflowTests(unittest.TestCase):
    def run_workflow(self, download_error=None):
        scope = launcher()
        progress = MagicMock()
        comp = Composition()
        items = [Article('Title', 'Body', 'https://example.test', 1)] * 5
        with tempfile.TemporaryDirectory() as directory:
            docx = Path(directory) / 'digest_06_11.docx'
            docx.write_bytes(b'test')
            scope['_ask_options'] = lambda comp: {'docx': str(docx), 'clip_name': ''}
            scope['_report_error'] = MagicMock()
            with patch('resolve_digest.progress.create_progress', return_value=progress), \
                 patch.object(fusion, 'current_timeline_composition', return_value=comp), \
                 patch.object(fusion, 'update_composition') as update, \
                 patch('resolve_digest.docx_parser.parse_docx', return_value=items), \
                 patch('resolve_digest.output.digest_output_directory', return_value=Path(directory)), \
                 patch('resolve_digest.article_images.download_all_article_images',
                       return_value=([Path(directory) / 'photo_01.jpg'], ['https://example.test/a.jpg']),
                       side_effect=download_error):
                scope['run']()
                return progress, update, scope['_report_error']

    def test_success_disables_cancel_before_fusion_write(self):
        progress, update, report = self.run_workflow()
        update.assert_called_once()
        self.assertFalse(progress.update.call_args.kwargs['cancellable'])
        self.assertEqual(progress.finish.call_args.args[0], 'success')
        report.assert_not_called()

    def test_cancel_does_not_modify_composition(self):
        progress, update, report = self.run_workflow(ProgressCancelled('cancel'))
        update.assert_not_called()
        self.assertEqual(progress.finish.call_args.args[0], 'cancelled')
        report.assert_not_called()

    def test_download_failure_routes_error_to_progress_window(self):
        progress, update, report = self.run_workflow(RuntimeError('server unavailable'))
        update.assert_not_called()
        self.assertIs(report.call_args.args[3], progress)
        self.assertIn('server unavailable', str(report.call_args.args[2]))
