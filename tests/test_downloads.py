import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from resolve_digest.article_images import article_image_urls, download_all_article_images, _get, ImageExtractionError
from resolve_digest.downloads import download_digest
from resolve_digest.models import Article
from resolve_digest.progress import ProgressCancelled


class DownloadTests(unittest.TestCase):
    def test_failed_middle_photo_keeps_numbers_and_downloads_rest(self):
        urls = ['https://example.test/1.jpg', 'https://example.test/2.jpg', 'https://example.test/3.jpg']
        response = MagicMock(headers={'Content-Type': 'image/jpeg'}, content=b'image')
        failures = []
        with tempfile.TemporaryDirectory() as directory, \
             patch('resolve_digest.article_images.article_image_urls', return_value=urls), \
             patch('resolve_digest.article_images._get', side_effect=[response, ImageExtractionError('HTTP 404'), response]):
            paths, saved = download_all_article_images('https://example.test', Path(directory),
                                                       on_error=lambda *args: failures.append(args))
            self.assertEqual([p.name for p in paths], ['photo_01.jpg', 'photo_03.jpg'])
            self.assertEqual(saved, [urls[0], urls[2]])
            self.assertEqual(failures[0][0:2], (2, urls[1]))

    def test_failed_article_does_not_stop_later_articles_and_report(self):
        items = [Article(str(i), 'body', f'https://example.test/{i}', 1) for i in range(5)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'photo_01.jpg'
            with patch('resolve_digest.article_images.download_all_article_images', side_effect=[
                ImageExtractionError('HTTPS failed'), ([path], ['url']), ([path], ['url']),
                ([path], ['url']), ([path], ['url'])]) as download:
                downloaded, failures, report = download_digest(items, Path(directory))
            self.assertEqual(download.call_count, 5)
            self.assertEqual(len(downloaded), 4)
            self.assertEqual(len(failures), 1)
            text = report.read_text(encoding='utf-8-sig')
            self.assertIn('HTTPS failed', text)
            self.assertIn(items[0].url, text)
            self.assertIn('Новость 5', text)

    def test_missing_selected_photo_is_reported_after_all_articles(self):
        items = [Article('title', 'body', 'https://example.test', 9)] * 5
        with tempfile.TemporaryDirectory() as directory, patch(
            'resolve_digest.article_images.download_all_article_images',
            return_value=([Path('photo_01.jpg')], ['url'])) as download:
            _, failures, _ = download_digest(items, Path(directory))
            self.assertEqual(download.call_count, 5)
            self.assertEqual(len(failures), 5)

    def test_cancellation_stops_batch(self):
        items = [Article('title', 'body', 'https://example.test', 1)] * 5
        with tempfile.TemporaryDirectory() as directory, patch(
            'resolve_digest.article_images.download_all_article_images', side_effect=ProgressCancelled()) as download:
            with self.assertRaises(ProgressCancelled):
                download_digest(items, Path(directory))
            self.assertEqual(download.call_count, 1)

    def test_ssl_eof_retries_but_bad_certificate_does_not(self):
        session = MagicMock()
        session.get.side_effect = [requests.exceptions.SSLError('UNEXPECTED_EOF_WHILE_READING'), MagicMock()]
        with patch('resolve_digest.article_images.time.sleep'):
            _get(session, 'https://example.test', label='test')
        self.assertEqual(session.get.call_count, 2)
        session.reset_mock()
        session.get.side_effect = requests.exceptions.SSLError('CERTIFICATE_VERIFY_FAILED')
        with self.assertRaises(ImageExtractionError):
            _get(session, 'https://example.test', label='test')
        self.assertEqual(session.get.call_count, 1)


class ExtractionTests(unittest.TestCase):
    def extract(self, html):
        response = MagicMock(text=html, url='https://example.test/redirect/news/')
        with patch('resolve_digest.article_images._get', return_value=response):
            return article_image_urls('https://example.test/old')

    def test_media_polytech_container_excludes_author(self):
        self.assertEqual(self.extract('''<div class="article-item__body">
            <div class="article_content"><p><img src="/1.jpg"></p><img src="/2.jpg"></div>
            <img src="/author.jpg"></div>'''), ['https://example.test/1.jpg', 'https://example.test/2.jpg'])

    def test_lazy_images_srcset_picture_and_redirect(self):
        self.assertEqual(self.extract('''<article><img src="data:image/gif;base64,aaa" data-src="photo.jpg">
            <img src="small.jpg" srcset="small.jpg 320w, big.jpg 1600w">
            <picture><source srcset="picture.jpg 1200w"><img src="placeholder.gif"></picture>
            </article>'''), ['https://example.test/redirect/news/photo.jpg',
                             'https://example.test/redirect/news/big.jpg',
                             'https://example.test/redirect/news/picture.jpg'])

    def test_heading_fallback_avoids_page_logo(self):
        self.assertEqual(self.extract('''<header><img src="/logo.jpg"></header>
            <div><h1>Title</h1><p>Article</p><img src="/photo.jpg"></div>'''),
            ['https://example.test/photo.jpg'])

    def test_structured_article_images(self):
        self.assertEqual(self.extract('''<script type="application/ld+json">
            {"@graph":[{"@type":"NewsArticle","image":[{"url":"/1.jpg"},"/2.jpg"]}]}</script>'''),
            ['https://example.test/1.jpg', 'https://example.test/2.jpg'])

    def test_metadata_fallback(self):
        self.assertEqual(self.extract('<meta property="og:image" content="/cover.jpg">'),
                         ['https://example.test/cover.jpg'])
