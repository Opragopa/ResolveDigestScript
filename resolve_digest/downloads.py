"""Best-effort digest downloads and a persistent, human-readable report."""
from pathlib import Path

from . import article_images
from .article_images import ImageExtractionError
from .models import DownloadedArticle


def download_digest(articles, cache, session=None, on_progress=None):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    report = cache / "download_report.txt"
    lines = ["Отчёт загрузки Resolve Digest"]
    downloaded, failures = [], []

    def save_report():
        report.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")

    save_report()
    for index, article in enumerate(articles, start=1):
        lines.append(f"\nНовость {index}: {article.title}\n{article.url}")

        def progress(done, total, message):
            if on_progress:
                on_progress(index, article, done, total, message)

        def failed(frame, url, reason):
            message = f"Новость {index}, фото {frame}: НЕ СКАЧАНО\n{url}\n{reason}"
            failures.append(message)
            lines.append(message)
            save_report()

        try:
            paths, urls = article_images.download_all_article_images(
                article.url, cache / f"news_{index:02d}", session=session,
                on_progress=progress, on_error=failed)
        except (ImageExtractionError, OSError) as error:
            failed("—", article.url, str(error))
            continue
        for path, url in zip(paths, urls):
            lines.append(f"СКАЧАНО: {path.name}\n{url}\n{path}")
        # Original numbers are kept on disk even when a middle photo failed.
        selected_name = f"photo_{article.photo_number:02d}.jpg"
        if not any(path.name == selected_name for path in paths):
            message = f"Новость {index}: выбранное фото №{article.photo_number} недоступно: {article.url}"
            lines.append(message)
            failures.append(message)
        if paths:
            downloaded.append(DownloadedArticle(article, paths[0], urls[0], len(paths)))
        save_report()
    lines.append(f"\nСкачано фотографий: {sum(item.image_count for item in downloaded)}")
    lines.append(f"Замечаний: {len(failures)}")
    if failures:
        lines.append("Fusion не обновлён: загрузка выпуска неполная. Номера фото на диске сохранены.")
    save_report()
    return downloaded, failures, report
