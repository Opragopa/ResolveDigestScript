from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .article_images import download_all_article_images
from .docx_parser import DocumentFormatError, parse_docx
from .fusion import current_timeline_composition, update_composition
from .models import DownloadedArticle


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill a five-news Fusion template from a DOCX file.")
    parser.add_argument("docx", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("cache"))
    parser.add_argument("--clip-name", help="Optional exact timeline clip name containing the Fusion comp")
    parser.add_argument("--dry-run", action="store_true", help="Parse and download only; do not edit Resolve")
    args = parser.parse_args()
    try:
        articles = parse_docx(args.docx)
        downloaded: list[DownloadedArticle] = []
        for index, article in enumerate(articles, start=1):
            paths, image_urls = download_all_article_images(
                article.url, args.cache / f"news_{index:02d}"
            )
            selected_frame = article.photo_number - 1
            if selected_frame >= len(paths):
                raise RuntimeError(
                    f"Requested photo #{article.photo_number}, but the article contains only "
                    f"{len(paths)} photos: {article.url}"
                )
            downloaded.append(
                DownloadedArticle(
                    article,
                    paths[0],
                    image_urls[0],
                    len(paths),
                )
            )
            print(
                f"[{index}/5] downloaded {len(paths)} photos; "
                f"selected photo #{article.photo_number}: {paths[0].parent}"
            )
        if args.dry_run:
            print("READY: DOCX and all five images are valid; Resolve was not changed.")
            return 0
        update_composition(current_timeline_composition(args.clip_name), downloaded)
        print("DONE: five title/body/image groups updated in Fusion.")
        return 0
    except (DocumentFormatError, RuntimeError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
