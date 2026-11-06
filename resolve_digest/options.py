"""Local preferences and a Windows options dialog, independent of Qt."""
import base64
import json
from pathlib import Path
import subprocess

DEFAULTS = {"body_gap_pixels": 80.0, "auto_update": True, "docx": "", "layout_only": False}


def load_preferences(directory):
    path = Path(directory) / "resolve_digest.local.json"
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise ValueError("Настройки должны быть объектом JSON")
        return {**DEFAULTS, **values}
    except FileNotFoundError:
        return dict(DEFAULTS)
    except (ValueError, OSError) as error:
        print("Resolve Digest: не удалось прочитать настройки: " + str(error))
        return dict(DEFAULTS)


def ask_windows_options(directory, update_status=""):
    source = Path(__file__).with_name("options_window.ps1").read_text(encoding="utf-8-sig")
    command = base64.b64encode(source.encode("utf-16-le")).decode("ascii")
    prefs = load_preferences(directory)
    prefs["update_status"] = update_status
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-EncodedCommand", command],
        input=json.dumps(prefs, ensure_ascii=False),
        capture_output=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW, check=False,
    )
    if result.returncode:
        raise RuntimeError("Не удалось открыть настройки: " + result.stderr.strip())
    if not result.stdout.strip():
        return None
    options = json.loads(result.stdout)
    path = Path(directory) / "resolve_digest.local.json"
    path.write_text(json.dumps(options, ensure_ascii=False, indent=2), encoding="utf-8")
    return options
