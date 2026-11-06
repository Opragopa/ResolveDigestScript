"""Fetch original editorial photos from a news article page."""
from __future__ import annotations

from pathlib import Path
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
HEADERS = {"User-Agent": "ResolveDigestScript/1.0 (+local editorial automation)"}
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


class ImageExtractionError(RuntimeError):
    pass


def _get(client, url, *, label, notify=None, referer=None):
    """Retry transient GET failures visibly; never retry cancellation callbacks."""
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if notify:
            notify(f"{label}: попытка {attempt}/{MAX_ATTEMPTS}")
        response = None
        delay = 2 ** attempt
        try:
            response = client.get(url, headers=headers, timeout=(15, 60))
            response.raise_for_status()
            return response
        except requests.exceptions.SSLError as error:
            raise ImageExtractionError(f"Ошибка проверки HTTPS-сертификата: {url}") from error
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as error:
            failure = error
            reason = "Сервер не ответил вовремя или соединение прервалось"
        except requests.exceptions.HTTPError as error:
            failure = error
            status = response.status_code
            if status not in RETRY_STATUSES:
                response.close()
                if status in (401, 403):
                    raise ImageExtractionError(
                        f"Сайт отказал в доступе (HTTP {status}). Проверьте открытие статьи в браузере: {url}"
                    ) from error
                raise ImageExtractionError(f"Ошибка HTTP {status}: {url}") from error
            reason = f"Сайт временно недоступен (HTTP {status})"
            try:
                delay = min(30, max(delay, float(response.headers.get("Retry-After", 0))))
            except (TypeError, ValueError):
                pass
        if response is not None:
            response.close()
        if attempt == MAX_ATTEMPTS:
            raise ImageExtractionError(f"{reason}. Выполнено попыток: {MAX_ATTEMPTS}.\n{url}") from failure
        print(f"Resolve Digest: {reason}; retry {attempt + 1}/{MAX_ATTEMPTS}: {url}")
        # One-second steps allow Cancel to interrupt the retry delay.
        remaining = delay
        while remaining > 0:
            if notify:
                notify(f"{reason}. Повтор {attempt + 1}/{MAX_ATTEMPTS} через {remaining:.0f} с")
            step = min(1, remaining)
            time.sleep(step)
            remaining -= step


def _client(session: requests.Session | None = None) -> requests.Session:
    """Return a session that never inherits proxy settings from the host."""
    client = session or requests.Session()
    # Equivalent to running requests with a "no proxy" flag.  Resolve can
    # inherit SOCKS_PROXY/HTTPS_PROXY from macOS or a launcher; Requests then
    # tries to load PySocks even though this script must make direct requests.
    client.trust_env = False
    return client


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


def article_image_urls(article_url: str, session: requests.Session | None = None,
                       on_status=None) -> list[str]:
    """Extract unique content images, preserving their visual order.

    The selectors intentionally prefer SPbPU article containers and only fall
    back to ``article``.  This prevents site chrome/logo images being counted.
    """
    client = _client(session)
    response = _get(client, article_url, label="Открытие статьи", notify=on_status)
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
    client = _client(session)
    urls = article_image_urls(article_url, client)
    if photo_number > len(urls):
        raise ImageExtractionError(
            f"Requested photo #{photo_number}, but the article contains only {len(urls)} photos: {article_url}"
        )
    image_url = urls[photo_number - 1]
    response = _get(client, image_url, label=f"Загрузка фото {photo_number}", referer=article_url)
    content_type = response.headers.get("Content-Type", "").lower()
    if content_type and not content_type.startswith("image/"):
        raise ImageExtractionError(f"Selected URL is not an image ({content_type}): {image_url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return image_url


def download_all_article_images(article_url: str, destination_dir: Path,
                                session: requests.Session | None = None,
                                on_progress=None) -> tuple[list[Path], list[str]]:
    """Download every content image as one zero-based Loader sequence.

    Each article gets its own directory so Fusion cannot combine images from
    different news items into the same numbered sequence.
    """
    client = _client(session)
    if on_progress:
        on_progress(0, 0, "Получение списка фотографий…")
    def page_status(message):
        if on_progress:
            on_progress(0, 0, message)
    urls = article_image_urls(article_url, client, on_status=page_status)
    if on_progress:
        on_progress(0, len(urls), f"Найдено фотографий: {len(urls)}")
    destination_dir.mkdir(parents=True, exist_ok=True)

    # Do not let images left by an earlier run extend the new Loader sequence.
    for stale in destination_dir.glob("photo_*.jpg"):
        if stale.is_file():
            stale.unlink()

    paths: list[Path] = []
    for frame, image_url in enumerate(urls, start=1):
        if on_progress:
            on_progress(frame - 1, len(urls), f"Загрузка фото {frame}/{len(urls)}")
        def image_status(message):
            if on_progress:
                on_progress(frame - 1, len(urls), message)
        response = _get(client, image_url, label=f"Загрузка фото {frame}/{len(urls)}",
                        notify=image_status, referer=article_url)
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and not content_type.startswith("image/"):
            raise ImageExtractionError(f"Selected URL is not an image ({content_type}): {image_url}")
        if on_progress:
            on_progress(frame - 1, len(urls), f"Сохранение фото {frame}/{len(urls)}")
        path = destination_dir / f"photo_{frame:02d}.jpg"
        path.write_bytes(response.content)
        paths.append(path)
        if on_progress:
            on_progress(frame, len(urls), f"Сохранено фото {frame}/{len(urls)}")
    return paths, urls
