import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import requests

from resolve_digest.article_images import _client, _get, ImageExtractionError, download_all_article_images


class ArticleImageClientTests(unittest.TestCase):
    def test_timeout_retries_and_reports_attempts(self):
        session = MagicMock()
        response = MagicMock()
        session.get.side_effect = [requests.exceptions.ReadTimeout(), response]
        messages = []
        with patch('resolve_digest.article_images.time.sleep'):
            self.assertIs(_get(session, 'https://example.test', label='Статья', notify=messages.append), response)
        self.assertEqual(session.get.call_count, 2)
        self.assertTrue(any('2/3' in message for message in messages))
        self.assertEqual(session.get.call_args.kwargs['timeout'], (15, 60))

    def test_retry_exhaustion_has_readable_error(self):
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ReadTimeout('read timed out')
        with patch('resolve_digest.article_images.time.sleep'):
            with self.assertRaisesRegex(ImageExtractionError, 'Выполнено попыток: 3'):
                _get(session, 'https://example.test', label='Статья')
        self.assertEqual(session.get.call_count, 3)

    def test_access_denied_is_not_retried(self):
        session = MagicMock()
        response = session.get.return_value
        response.status_code = 403
        response.raise_for_status.side_effect = requests.exceptions.HTTPError()
        with self.assertRaisesRegex(ImageExtractionError, 'HTTP 403'):
            _get(session, 'https://example.test', label='Статья')
        self.assertEqual(session.get.call_count, 1)
        response.close.assert_called_once()

    def test_server_error_is_retried_and_failed_response_closed(self):
        session = MagicMock()
        failed, success = MagicMock(), MagicMock()
        failed.status_code = 503
        failed.headers = {'Retry-After': '3'}
        failed.raise_for_status.side_effect = requests.exceptions.HTTPError()
        session.get.side_effect = [failed, success]
        with patch('resolve_digest.article_images.time.sleep') as sleep:
            self.assertIs(_get(session, 'https://example.test', label='Фото'), success)
        self.assertEqual(sleep.call_count, 3)
        failed.close.assert_called_once()

    def test_cancel_during_retry_delay_does_not_start_next_request(self):
        from resolve_digest.progress import ProgressCancelled
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ReadTimeout()
        def notify(message):
            if 'Повтор' in message:
                raise ProgressCancelled()
        with self.assertRaises(ProgressCancelled):
            _get(session, 'https://example.test', label='Фото', notify=notify)
        self.assertEqual(session.get.call_count, 1)

    def test_image_requests_send_article_referer(self):
        session = MagicMock()
        _get(session, 'https://example.test/a.jpg', label='Фото', referer='https://example.test/news')
        self.assertEqual(session.get.call_args.kwargs['headers']['Referer'], 'https://example.test/news')

    def test_disables_environment_proxies_on_new_session(self):
        self.assertFalse(_client().trust_env)

    def test_disables_environment_proxies_on_provided_session(self):
        class Session:
            trust_env = True

        session = Session()
        self.assertIs(_client(session), session)
        self.assertFalse(session.trust_env)

    def test_downloads_all_images_as_zero_based_sequence(self):
        class Response:
            headers = {"Content-Type": "image/jpeg"}

            def __init__(self, content):
                self.content = content

            def raise_for_status(self):
                pass

        class Session:
            trust_env = True

            def get(self, url, **_kwargs):
                return Response(url.encode())

        with tempfile.TemporaryDirectory() as directory, patch(
            "resolve_digest.article_images.article_image_urls",
            return_value=["https://example.test/a.jpg", "https://example.test/b.jpg"],
        ):
            paths, urls = download_all_article_images(
                "https://example.test/news", Path(directory), Session()
            )
            self.assertEqual(
                [path.name for path in paths],
                ["photo_01.jpg", "photo_02.jpg"],
            )
            self.assertEqual(len(urls), 2)
            self.assertEqual(paths[1].read_bytes(), b"https://example.test/b.jpg")
