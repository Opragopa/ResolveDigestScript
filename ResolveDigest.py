"""DaVinci Resolve menu entry point for Resolve Digest.

Put this file together with the ``resolve_digest`` directory into Resolve's
``Fusion/Scripts/Utility/ResolveDigest`` folder.  It intentionally has no CLI
arguments: all input is collected in Resolve.
"""
import os
import subprocess
import sys
import traceback
import tempfile
from datetime import datetime
from pathlib import Path

BODY_GAP_PIXELS = 80.0


def _script_directory() -> Path:
    """Resolve executes menu scripts with ``exec`` and omits ``__file__``."""
    candidates = []
    if globals().get("__file__"):
        candidates.append(Path(__file__).resolve().parent)
    # This works even when the menu supplies neither __file__ nor API globals.
    if os.name == "nt" and os.environ.get("APPDATA"):
        utility = Path(os.environ["APPDATA"]) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts" / "Utility"
        candidates.extend(utility / name for name in ("ResolveDigestScript", "ResolveDigest", ""))
    for candidate in candidates:
        if (candidate / "resolve_digest" / "__init__.py").is_file():
            return candidate
    fusion = globals().get("fusion") or globals().get("fu")
    resolve = globals().get("resolve")
    if fusion is None and resolve is not None:
        fusion = resolve.Fusion()
    if fusion is None:
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        api_modules = program_data / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Developer" / "Scripting" / "Modules"
        if str(api_modules) not in sys.path:
            sys.path.insert(0, str(api_modules))
        import DaVinciResolveScript as dvr
        resolve = dvr.scriptapp("Resolve")
        fusion = resolve.Fusion() if resolve else None
    utility = fusion.MapPath("Scripts:/Utility") if fusion else None
    if utility:
        for name in ("ResolveDigestScript", "ResolveDigest", ""):
            candidate = Path(utility) / name
            if (candidate / "resolve_digest" / "__init__.py").is_file():
                return candidate
    raise RuntimeError("Не найдена папка resolve_digest рядом с ResolveDigest.py. Скопируйте всю папку скрипта.")


def _windows_message(title, text):
    """Centre the actual message box on the primary work area on activation.

    A thread-local CBT hook avoids Qt dependencies and stale saved positions.
    Pointer-sized signatures are essential in Resolve's 64-bit Python.
    """
    import ctypes
    from ctypes import wintypes as w
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, w.WPARAM, w.LPARAM)
    user.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, w.HINSTANCE, w.DWORD]
    user.SetWindowsHookExW.restype = w.HANDLE
    user.CallNextHookEx.argtypes = [w.HANDLE, ctypes.c_int, w.WPARAM, w.LPARAM]
    user.CallNextHookEx.restype = ctypes.c_ssize_t
    user.UnhookWindowsHookEx.argtypes = [w.HANDLE]
    user.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user.SystemParametersInfoW.argtypes = [w.UINT, w.UINT, w.LPVOID, w.UINT]
    user.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, w.UINT]
    user.MessageBoxW.argtypes = [w.HWND, w.LPCWSTR, w.LPCWSTR, w.UINT]
    kernel.GetCurrentThreadId.restype = w.DWORD

    @callback_type
    def centre(code, hwnd, data):
        if code == 5:  # HCBT_ACTIVATE; SPI_GETWORKAREA always means primary.
            area, rect = w.RECT(), w.RECT()
            if (user.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0)
                    and user.GetWindowRect(hwnd, ctypes.byref(rect))):
                x = area.left + max(0, (area.right - area.left - rect.right + rect.left) // 2)
                y = area.top + max(0, (area.bottom - area.top - rect.bottom + rect.top) // 2)
                user.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0015)
        return user.CallNextHookEx(None, code, hwnd, data)

    hook = user.SetWindowsHookExW(5, centre, None, kernel.GetCurrentThreadId())
    if not hook:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        # TOPMOST | SETFOREGROUND | MB_OK; no QApplication is needed.
        if not user.MessageBoxW(None, text, title, 0x00050000):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        user.UnhookWindowsHookEx(hook)


def _message(comp, title, text):
    print("{}: {}".format(title, text))
    if os.name == "nt":
        try:
            _windows_message(title, text)
            return
        except Exception:
            traceback.print_exc()
    try:
        from PySide2.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is not None:
            dialog = QMessageBox(QMessageBox.Information, title, text, QMessageBox.Ok)
            dialog.adjustSize()
            screen = app.primaryScreen()
            if screen:
                dialog.move(screen.availableGeometry().center() - dialog.rect().center())
            dialog.exec_()
            return
    except Exception:
        traceback.print_exc()
    if comp is not None:
        comp.AskUser(title, {
            1.0: {"ID": "message", "Name": text, "Type": "Text", "Default": "Нажмите OK, чтобы закрыть."},
        })


def _report_error(comp, stage, error, progress=None):
    details = "{}\nPython: {}\nExecutable: {}\nStage: {}\n{}\n".format(
        datetime.now().isoformat(), sys.version, sys.executable, stage, traceback.format_exc())
    print(details)
    log_path = None
    for directory in (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ResolveDigest",
                      Path(tempfile.gettempdir()) / "ResolveDigest"):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            log_path = directory / "ResolveDigest.log"
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(details)
            break
        except Exception:
            log_path = None
    text = "Этап: {}\n{}: {}".format(stage, type(error).__name__, error)
    if isinstance(error, ImportError):
        text += "\nУстановите requirements.txt в Python, которым пользуется Resolve."
    if isinstance(error, PermissionError):
        text += "\nПроверьте доступ к DOCX и папке сохранения, подключение диска Z:."
    if stage == "Обновление Fusion-композиции":
        text += "\nЕсли часть правок применилась, отмените группу Resolve Digest через Undo в Fusion."
    text += "\n\nЖурнал: {}".format(log_path) if log_path else "\nПодробности — в консоли Resolve."
    if progress is not None:
        try:
            progress.finish("error", "Не удалось собрать выпуск", text)
            return
        except Exception:
            traceback.print_exc()
    try:
        _message(comp, "Resolve Digest — ошибка", text)
    except Exception:
        traceback.print_exc()


def _ask_options(comp):
    """Use an owned Windows file chooser, otherwise Qt or Fusion."""
    if os.name == "nt":
        from resolve_digest.options import ask_windows_options
        return ask_windows_options(_script_directory(), globals().get("_DIGEST_UPDATE_STATUS", ""))
    try:
        from PySide2.QtCore import Qt
        from PySide2.QtWidgets import QApplication, QFileDialog
        app = QApplication.instance()
        if app is None:
            raise ImportError("Qt QApplication is not available")
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


def _refresh_installation(directory, force=False):
    # Resolve keeps imported modules alive between menu launches. Drop cached
    # package objects so the next run uses the files now installed on disk.
    import importlib
    importlib.invalidate_caches()
    for name in tuple(sys.modules):
        if name == "resolve_digest" or name.startswith("resolve_digest."):
            del sys.modules[name]
    from resolve_digest.options import load_preferences
    skip = globals().pop("_DIGEST_SKIP_UPDATE", False)
    if skip:
        return False
    if not force and not load_preferences(directory).get("auto_update", True):
        globals()["_DIGEST_UPDATE_STATUS"] = "Автообновление отключено."
        return False
    from resolve_digest.updater import update_checkout
    updated, message = update_checkout(directory)
    globals()["_DIGEST_UPDATE_STATUS"] = message
    print("Resolve Digest: " + message)
    if not updated:
        return False
    entry = Path(directory) / "ResolveDigest.py"
    scope = {"__name__": "__main__", "__file__": str(entry), "_DIGEST_SKIP_UPDATE": True,
             "_DIGEST_UPDATE_STATUS": message}
    for name in ("resolve", "fusion", "fu"):
        if name in globals():
            scope[name] = globals()[name]
    exec(compile(entry.read_text(encoding="utf-8"), str(entry), "exec"), scope)
    return True


def run() -> None:
    comp = None
    progress = None
    download_session = None
    cancelled_errors = ()
    stage = "Запуск и поиск папки скрипта"
    try:
        if sys.version_info < (3, 9):
            raise RuntimeError("Для этого скрипта нужен Python 3.9 или новее. Текущий: " + sys.version)
        script_directory = _script_directory()
        if str(script_directory) not in sys.path:
            sys.path.insert(0, str(script_directory))
        if _refresh_installation(script_directory):
            return
        from resolve_digest.progress import create_progress, ProgressCancelled
        cancelled_errors = (ProgressCancelled,)
        stage = "Загрузка модулей и зависимостей"
        import requests
        from resolve_digest.downloads import download_digest
        from resolve_digest.docx_parser import parse_docx
        from resolve_digest import fusion as adapter
        from resolve_digest.output import digest_output_directory
        host = globals().get("resolve")
        if host is None:
            fusion_host = globals().get("fusion") or globals().get("fu")
            if fusion_host is not None:
                host = fusion_host.GetResolve()
        adapter.set_resolve_instance(host)
        current_timeline_composition = adapter.current_timeline_composition
        stage = "Проверка проекта и Fusion-композиции"
        comp = current_timeline_composition()
        stage = "Настройки выпуска"
        options = _ask_options(comp)
        while options and options.get("action") == "check_updates":
            stage = "Проверка обновлений"
            if _refresh_installation(script_directory, force=True):
                return
            options = _ask_options(comp)
        if not options:
            return
        stage = "Открытие окна прогресса"
        progress = create_progress()
        progress.update(2, "Проверка проекта и шаблона Fusion")
        clip_name = options.get("clip_name", "").strip() or None
        if clip_name:
            comp = current_timeline_composition(clip_name)
        stage = "Проверка шаблона Fusion"
        adapter.validate_composition(comp)
        gap = float(options.get("body_gap_pixels", BODY_GAP_PIXELS))
        if options.get("layout_only", False):
            stage = "Обновление Fusion-композиции"
            progress.update(30, "Верстка текста в границах фото", "Отступ: {:g} px".format(gap), cancellable=False)
            adapter.reflow_composition(comp, gap)
            progress.finish("success", "Отступы и границы текста обновлены", "Отступ title → body: {:g} px".format(gap))
            return
        docx_path = Path(options["docx"])
        if not docx_path.is_file():
            raise FileNotFoundError("Выберите существующий DOCX-файл: " + str(docx_path))
        stage = "Чтение DOCX"
        progress.update(5, stage, docx_path.name)
        articles = parse_docx(docx_path)
        stage = "Подготовка папки изображений"
        cache = digest_output_directory(docx_path)
        progress.update(8, stage, str(cache))
        if os.name == "nt" and not Path(cache.anchor).exists():
            raise RuntimeError("Диск сохранения недоступен: " + cache.anchor)
        cache.mkdir(parents=True, exist_ok=True)
        download_session = requests.Session()
        download_session.trust_env = False
        def image_progress(index, article, done, total, message):
            fraction = done / total if total else 0
            percent = 10 + ((index - 1 + fraction) / len(articles)) * 80
            progress.update(percent, "Новость {}/{}: {}".format(index, len(articles), message),
                            article.title + "\n" + article.url)
        downloaded, failures, report = download_digest(
            articles, cache, session=download_session, on_progress=image_progress)
        progress.check_cancelled()
        if failures:
            progress.finish("error", "Загрузка завершена с пропусками",
                            "Всё доступное сохранено. Fusion не обновлён.\n"
                            + "\n\n".join(failures) + "\n\nОтчёт: " + str(report))
            return
        stage = "Обновление Fusion-композиции"
        # Cancellation stops at this boundary: don't interrupt a partial edit.
        progress.update(95, stage, "Запись текста и изображений. Дождитесь завершения.", cancellable=False)
        adapter.update_composition(comp, downloaded, body_gap_pixels=gap, constrain_to_photo=True)
        progress.finish("success", "Готово: пять новостей обновлены", "Рендер запустите в Deliver вручную.\nИзображения: " + str(cache))
    except cancelled_errors:
        try:
            progress.finish("cancelled", "Операция отменена", "Композиция не изменена. Уже скачанные файлы остаются на диске.")
        except Exception as error:
            _report_error(comp, "Отмена загрузки", error)
    except Exception as error:
        if progress is None:
            _report_error(comp, stage, error)
        else:
            _report_error(comp, stage, error, progress)
    finally:
        if download_session is not None:
            download_session.close()


run()
