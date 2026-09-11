from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .article_images import download_article_image
from .docx_parser import DocumentFormatError, parse_docx
from .fusion import current_timeline_composition, update_composition
from .models import DownloadedArticle


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill a six-news Fusion template from a DOCX file.")
    parser.add_argument("docx", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("cache"))
    parser.add_argument("--clip-name", help="Optional exact timeline clip name containing the Fusion comp")
    parser.add_argument("--dry-run", action="store_true", help="Parse and download only; do not edit Resolve")
    args = parser.parse_args()
    try:
        articles = parse_docx(args.docx)
        downloaded: list[DownloadedArticle] = []
        for index, article in enumerate(articles, start=1):
            path = args.cache / f"news_{index:02d}.jpg"
            image_url = download_article_image(article.url, article.photo_number, path)
            downloaded.append(DownloadedArticle(article, path, image_url))
            print(f"[{index}/6] downloaded photo #{article.photo_number}: {path}")
        if args.dry_run:
            print("READY: DOCX and all six images are valid; Resolve was not changed.")
            return 0
        update_composition(current_timeline_composition(args.clip_name), downloaded)
        print("DONE: six title/body/image groups updated in Fusion.")
        return 0
    except (DocumentFormatError, RuntimeError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
