"""DaVinci Resolve menu entry point for Resolve Digest.

Put this file together with the ``resolve_digest`` directory into Resolve's
``Fusion/Scripts/Utility/ResolveDigest`` folder.  It intentionally has no CLI
arguments: all input is collected in Resolve.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _script_directory() -> Path:
    """Resolve executes menu scripts with ``exec`` and omits ``__file__``."""
    try:
        return Path(__file__).resolve().parent
    except NameError:
        # `Scripts:/` is Resolve/Fusion's documented path map.  This branch is
        # used only when the script is selected from Workspace > Scripts.
        fusion = globals().get("fusion")
        if fusion is None:
            # Resolve's menu runner does not always populate PYTHONPATH.  Add
            # its documented Windows API module location before importing.
            program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
            api_modules = program_data / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Developer" / "Scripting" / "Modules"
            if str(api_modules) not in sys.path:
                sys.path.insert(0, str(api_modules))
            import DaVinciResolveScript as dvr
            resolve = dvr.scriptapp("Resolve")
            fusion = resolve.Fusion() if resolve else None
        scripts_utility = fusion.MapPath("Scripts:/Utility") if fusion else None
        if not scripts_utility:
            raise RuntimeError("Cannot determine the Resolve Scripts folder.")
        # Both names are supported because older setup instructions used the
        # shorter folder name, while this repository is ResolveDigestScript.
        for folder_name in ("ResolveDigestScript", "ResolveDigest"):
            candidate = Path(scripts_utility) / folder_name
            if (candidate / "resolve_digest").is_dir():
                return candidate
        raise RuntimeError("ResolveDigestScript folder was not found under Scripts:/Utility.")


SCRIPT_DIRECTORY = _script_directory()
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))


def _message(comp, title: str, text: str) -> None:
    """Prefer a visible system dialog; retain Fusion's dialog as a fallback."""
    print(f"{title}: {text}")
    try:
        from PySide2.QtWidgets import QMessageBox
        QMessageBox.information(None, title, text)
        return
    except ImportError:
        pass
    comp.AskUser(title, {
        1.0: {"ID": "message", "Name": text, "Type": "Text", "Default": "Нажмите OK, чтобы закрыть."},
    })


def _ask_options(comp):
    """Use a standard foreground file chooser whenever Resolve provides Qt."""
    if os.name == "nt":
        # Resolve's embedded UI can restore a Fusion window at an unreachable
        # coordinate.  WinForms' OpenFileDialog is a real Windows dialog and
        # Windows places it on the active desktop instead.
        powershell = r'''Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = "Resolve Digest — выберите DOCX с 5 новостями"
$dialog.Filter = "Документы Word (*.docx)|*.docx"
$dialog.InitialDirectory = [Environment]::GetFolderPath('MyDocuments')
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Out.Write($dialog.FileName)
}'''
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", powershell],
            capture_output=True,
            text=True,
            check=False,
        )
        docx_path = result.stdout.strip()
        if not docx_path:
            return None
        document = Path(docx_path)
        return {
            "docx": str(document),
            "clip_name": "",
        }
    try:
        from PySide2.QtCore import Qt
        from PySide2.QtWidgets import QApplication, QFileDialog
        dialog = QFileDialog()
        dialog.setWindowTitle("Resolve Digest — выберите DOCX с 5 новостями")
        dialog.setDirectory(str(Path.home()))
        dialog.setNameFilter("Документы Word (*.docx)")
        dialog.setFileMode(QFileDialog.ExistingFile)
        # Native Windows dialogs can reopen at stale off-screen coordinates.
        # The Qt dialog lets us reliably centre the window on the active screen.
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
        dialog.resize(900, 650)
        app = QApplication.instance()
        screen = app.primaryScreen() if app else None
        if screen:
            available = screen.availableGeometry()
            dialog.move(available.center() - dialog.rect().center())
        if dialog.exec_() != QFileDialog.Accepted:
            return None
        document = Path(dialog.selectedFiles()[0])
        return {
            "docx": str(document),
            "clip_name": "",
        }
    except ImportError:
        pass
    # Older Resolve installations without Qt keep the previous Fusion dialog.
    return comp.AskUser("Собрать выпуск из DOCX", {
        1.0: {
            "ID": "docx", "Name": "DOCX с 5 новостями", "Type": "FileBrowse",
            "Default": "", "FileMask": "DOCX (*.docx)",
        },
        2.0: {
            "ID": "clip_name", "Name": "Имя Fusion Clip (необязательно)", "Type": "Text",
            "Default": "",
        },
    })


def run() -> None:
    # Imports live here so a missing Python package is shown as a useful Resolve
    # dialog rather than a silent failure while the Scripts menu is loading.
    try:
        from resolve_digest.article_images import download_all_article_images
        from resolve_digest.docx_parser import parse_docx
        from resolve_digest.fusion import current_timeline_composition, update_composition
        from resolve_digest.models import DownloadedArticle
        from resolve_digest.output import digest_output_directory
    except ImportError as error:
        print(f"Resolve Digest: missing dependency: {error}")
        return

    try:
        comp = current_timeline_composition()
        options = _ask_options(comp)
        if not options:
            return
        docx_path = Path(options["docx"])
        if not docx_path.is_file():
            _message(comp, "Resolve Digest", "Выберите существующий DOCX-файл.")
            return
        articles = parse_docx(docx_path)
        cache = digest_output_directory(docx_path)
        downloaded = []
        for index, article in enumerate(articles, start=1):
            news_dir = cache / f"news_{index:02d}"
            image_paths, image_urls = download_all_article_images(article.url, news_dir)
            selected_frame = article.photo_number - 1
            if selected_frame >= len(image_paths):
                raise RuntimeError(
                    f"Requested photo #{article.photo_number}, but the article contains only "
                    f"{len(image_paths)} photos: {article.url}"
                )
            downloaded.append(
                DownloadedArticle(article, image_paths[0], image_urls[0], len(image_paths))
            )
            print(
                f"Resolve Digest: {index}/5 downloaded {len(image_paths)} photos to {news_dir}; "
                f"initial Trim={selected_frame}-{selected_frame}"
            )
        clip_name = options["clip_name"].strip() or None
        update_composition(current_timeline_composition(clip_name), downloaded)
        _message(comp, "Resolve Digest", "Готово: пять новостей обновлены. Рендер запустите в Deliver вручную.")
    except Exception as error:
        # Nothing is hidden: the exact cause is also printed in Resolve's console.
        print(f"Resolve Digest ERROR: {error}")
        try:
            _message(comp, "Resolve Digest — ошибка", str(error))
        except Exception:
            pass


run()
