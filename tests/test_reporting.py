import json
import io
from contextlib import redirect_stdout, redirect_stderr
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resolve_digest.reporting import redact, report_diagnostic, retry_pending


class ReportingTests(unittest.TestCase):
    def test_cli_reports_download_failures_without_updating_fusion(self):
        from resolve_digest.main import main
        with patch('sys.argv', ['resolve_digest', 'digest.docx']), \
             patch('resolve_digest.main.retry_pending', return_value=''), \
             patch('resolve_digest.main.parse_docx', return_value=[]), \
             patch('resolve_digest.main.download_digest', return_value=([], ['HTTP 403'], Path('report.txt'))), \
             patch('resolve_digest.main.report_diagnostic', return_value='Saved') as report, \
             patch('resolve_digest.main.update_composition') as update, \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(), 1)
        report.assert_called_once()
        self.assertIn('HTTP 403', report.call_args.args[1])
        update.assert_not_called()

    def test_redacts_accounts_tokens_and_url_credentials(self):
        text = redact('C:\\Users\\Someone\\app.py ghp_12345 Authorization: BearerToken '
                      'https://user:password@example.test/photo.jpg?secret=123#fragment')
        for secret in ('Someone', 'ghp_12345', 'BearerToken', 'password', 'secret=123', '#fragment'):
            self.assertNotIn(secret, text)
        self.assertIn('https://example.test/photo.jpg', text)

    def config(self, directory, endpoint):
        (Path(directory) / 'diagnostics.json').write_text(json.dumps({'endpoint': endpoint}), encoding='utf-8')

    def test_unconfigured_report_is_saved_without_network(self):
        with tempfile.TemporaryDirectory() as folder, patch('resolve_digest.reporting.build_opener') as opener:
            self.config(folder, '')
            result = report_diagnostic('Download', 'Connection failed', folder, Path(folder) / 'reports')
            self.assertIn('нет сервиса', result)
            self.assertEqual(len(list((Path(folder) / 'reports').glob('*.json'))), 1)
            opener.assert_not_called()

    def test_success_sends_redacted_log_and_deduplicates_locally(self):
        with tempfile.TemporaryDirectory() as folder, patch('resolve_digest.reporting.build_opener') as opener:
            self.config(folder, 'https://relay.test/report')
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"issue_url":"https://github.com/Opragopa/ResolveDigestScript/issues/42"}'
            spool = Path(folder) / 'reports'
            result = report_diagnostic('Download', 'C:\\Users\\Someone\\app.py', folder, spool)
            self.assertIn('/42', result)
            sent = opener.return_value.open.call_args.args[0]
            self.assertNotIn('Someone', sent.data.decode('utf-8'))
            report_diagnostic('Download', 'C:\\Users\\Someone\\app.py', folder, spool)
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_network_failure_keeps_report_and_retries_on_next_launch(self):
        with tempfile.TemporaryDirectory() as folder, patch('resolve_digest.reporting.build_opener') as opener:
            self.config(folder, 'https://relay.test/report')
            spool = Path(folder) / 'reports'
            opener.return_value.open.side_effect = TimeoutError()
            self.assertIn('Не удалось', report_diagnostic('Download', 'Failed', folder, spool))
            self.assertEqual(len(list(spool.glob('*.json'))), 1)
            opener.return_value.open.side_effect = None
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"issue_url":"https://github.com/Opragopa/ResolveDigestScript/issues/42"}'
            self.assertIn('/42', retry_pending(folder, spool))
            self.assertEqual(retry_pending(folder, spool), '')

    def test_rejects_insecure_endpoint_without_network(self):
        with tempfile.TemporaryDirectory() as folder, patch('resolve_digest.reporting.build_opener') as opener:
            self.config(folder, 'http://relay.test/report')
            self.assertIn('HTTPS', report_diagnostic('Download', 'Failed', folder, Path(folder) / 'reports'))
            opener.assert_not_called()
