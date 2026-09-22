import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resolve_digest.article_images import _client, download_all_article_images


class ArticleImageClientTests(unittest.TestCase):
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
                ["photo_0000.jpg", "photo_0001.jpg"],
            )
            self.assertEqual(len(urls), 2)
            self.assertEqual(paths[1].read_bytes(), b"https://example.test/b.jpg")
