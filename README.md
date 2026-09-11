# Resolve Digest Script

Генератор выпуска из пяти новостей для одной Fusion-композиции в DaVinci Resolve.

## Один раз подготовить шаблон Resolve

В единственном Fusion Clip на `V1` переименуйте ноды:

```
title_01 … title_05     # Text+ с заголовками
body_01 … body_05       # Text+ с описаниями
image_01 … image_05     # Loader с картинками
```

`image_XX` обязательно должен быть **Loader**, а не MediaIn. Merge, анимация,
маски и Transform остаются как есть. Скрипт меняет только эти 18 входов.

## Формат DOCX

Пять повторяющихся блоков: заголовок, один или несколько абзацев описания,
адрес статьи и номер фотографии. URL и маркер разрешено держать в одной строке.

```
Заголовок новости
Описание новости. Может занимать несколько абзацев.
https://www.spbstu.ru/media/news/...
(фото 1)
```

Номер в `(фото 6)` — порядковый номер фото **в статье**, а не имя файла. Если
метки нет, выбирается первое содержательное фото статьи (не логотип сайта).
При недостаточном числе картинок для указанного номера запуск останавливается:
неверное фото не будет подставлено молча.

## Запуск прямо из DaVinci Resolve

Скопируйте **всю** папку проекта (файл `ResolveDigest.py`, папку
`resolve_digest` и `requirements.txt`) в пользовательскую папку скриптов:

```text
macOS: ~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/ResolveDigest/
Windows: %APPDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility\ResolveDigest\
```

Установите зависимости один раз в Python, которым пользуется Resolve. На macOS
обычно проще выполнить это в Terminal после перехода в скопированную папку:

```bash
python3 -m pip install -r requirements.txt
```

Перезапустите Resolve. Скрипт появится в меню **Workspace → Scripts → Utility
→ ResolveDigest → ResolveDigest**. Откройте проект и timeline, запустите его
и выберите DOCX. Никаких аргументов в Terminal для ежедневной работы не
требуется.

В современных версиях Resolve откроется обычное системное окно выбора DOCX
поверх программы. Загруженные изображения сохраняются рядом с документом в
папку `ResolveDigestCache`.

Если указанное имя Fusion Clip оставить пустым, скрипт обновит первую Fusion-
композицию на V1. Укажите имя клипа, чтобы явно защититься от выбора другой
композиции.

## Запуск из Terminal (для диагностики)

Установите зависимости в Python, которым запускаете скрипт:

```bash
python -m pip install -r requirements.txt
```

Сначала безопасно проверьте исходный DOCX и скачивание:

```bash
python -m resolve_digest.main /path/to/news.docx --cache /path/to/cache --dry-run
```

Затем откройте проект и нужный timeline в Resolve, оставьте Fusion Clip на
первой видеодорожке и выполните ту же команду без `--dry-run`:

```bash
python -m resolve_digest.main /path/to/news.docx --cache /path/to/cache --clip-name NEWS_TEMPLATE
```

Если имя клипа не указано, используется первая Fusion-композиция на V1.
Для запуска из меню Resolve скопируйте папку `resolve_digest` в папку скриптов
Resolve и запускайте `main.py` его встроенным Python; внешний Python должен
видеть `DaVinciResolveScript`.
