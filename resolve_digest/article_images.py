"""Fetch original editorial photos from a news article page."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
HEADERS = {"User-Agent": "ResolveDigestScript/1.0 (+local editorial automation)"}


class ImageExtractionError(RuntimeError):
    pass


def _is_image_url(value: str) -> bool:
    return urlparse(value).path.lower().endswith(IMAGE_EXTENSIONS)


def _image_url(image, page_url: str) -> str | None:
    link = image.find_parent("a", href=True)
    if link:
        candidate = urljoin(page_url, link["href"])
        if _is_image_url(candidate):
            return candidate
    for attribute in ("data-original", "data-src", "data-lazy-src", "src"):
        if image.get(attribute):
            return urljoin(page_url, image[attribute])
    return None


def article_image_urls(article_url: str, session: requests.Session | None = None) -> list[str]:
    """Extract unique content images, preserving their visual order.

    The selectors intentionally prefer SPbPU article containers and only fall
    back to ``article``.  This prevents site chrome/logo images being counted.
    """
    client = session or requests.Session()
    response = client.get(article_url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    container = soup.select_one(
        ".news-detail, .news-detail__content, .detail-text, .news-item-detail, article"
    )
    if container is None:
        raise ImageExtractionError(f"Could not locate the article body: {article_url}")

    urls: list[str] = []
    for image in container.find_all("img"):
        candidate = _image_url(image, article_url)
        if candidate and candidate not in urls:
            urls.append(candidate)
    if not urls:
        raise ImageExtractionError(f"No article images found: {article_url}")
    return urls


def download_article_image(article_url: str, photo_number: int, destination: Path,
                           session: requests.Session | None = None) -> str:
    if photo_number < 1:
        raise ImageExtractionError("Photo number must be at least 1")
    client = session or requests.Session()
    urls = article_image_urls(article_url, client)
    if photo_number > len(urls):
        raise ImageExtractionError(
            f"Requested photo #{photo_number}, but the article contains only {len(urls)} photos: {article_url}"
        )
    image_url = urls[photo_number - 1]
    response = client.get(image_url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").lower()
    if content_type and not content_type.startswith("image/"):
        raise ImageExtractionError(f"Selected URL is not an image ({content_type}): {image_url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return image_url
