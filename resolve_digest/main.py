from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from .downloads import download_digest
from .docx_parser import DocumentFormatError, parse_docx
from .fusion import current_timeline_composition, update_composition
from .reporting import report_diagnostic, retry_pending


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill a five-news Fusion template from a DOCX file.")
    parser.add_argument("docx", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("cache"))
    parser.add_argument("--clip-name", help="Optional exact timeline clip name containing the Fusion comp")
    parser.add_argument("--dry-run", action="store_true", help="Parse and download only; do not edit Resolve")
    parser.add_argument("--body-gap", type=float, default=80.0, help="Gap below title in pixels (default: 80)")
    args = parser.parse_args()
    try:
        retry_status = retry_pending()
        if retry_status:
            print(retry_status)
        articles = parse_docx(args.docx)
        downloaded, failures, report = download_digest(articles, args.cache)
        print(f"Отчёт загрузки: {report}")
        if failures:
            print("Загрузка завершена с пропусками. Всё доступное сохранено; Fusion не обновлён.", file=sys.stderr)
            print("\n\n".join(failures), file=sys.stderr)
            print(report_diagnostic('Загрузка завершена с пропусками', '\n\n'.join(failures)), file=sys.stderr)
            return 1
        if args.dry_run:
            print("READY: DOCX and all five images are valid; Resolve was not changed.")
            return 0
        update_composition(current_timeline_composition(args.clip_name), downloaded, body_gap_pixels=args.body_gap, constrain_to_photo=True)
        print("DONE: five title/body/image groups updated in Fusion.")
        return 0
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        print(report_diagnostic('Запуск из командной строки', traceback.format_exc()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
