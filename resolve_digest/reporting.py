"""Anonymous diagnostics via an operator-hosted relay; no GitHub keys on clients."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, build_opener, ProxyHandler


def redact(text):
    text = str(text)
    for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA'):
        value = os.environ.get(name)
        if value:
            text = re.sub(re.escape(value), '<local>', text, flags=re.I)
    text = re.sub(r'(?i)([A-Z]:[\\/]Users[\\/])[^\\/\s]+', r'\1<user>', text)
    text = re.sub(r'/Users/[^/\s]+|/home/[^/\s]+', '/home/<user>', text)
    text = re.sub(r'(?i)(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+', '<token>', text)
    text = re.sub(r'(?im)((?:authorization|password|token|secret|api[_-]?key)\s*[:=]\s*)[^\s,;]+', r'\1<redacted>', text)
    def clean_url(match):
        try:
            parts = urlsplit(match.group())
            host = parts.hostname or ''
            if parts.port:
                host += ':' + str(parts.port)
            return urlunsplit((parts.scheme, host, parts.path, '', ''))
        except ValueError:
            return '<url>'
    return re.sub(r'https?://[^\s<>"\']+', clean_url, text)


def report_diagnostic(stage, details, directory=None, spool=None):
    """Persist before sending. Return a user-visible result; never mask errors."""
    try:
        root = Path(directory) if directory else Path(__file__).resolve().parent.parent
        config = json.loads((root / 'diagnostics.json').read_text(encoding='utf-8'))
        endpoint = config.get('endpoint', '')
        spool = Path(spool) if spool else Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ResolveDigest' / 'reports'
        spool.mkdir(parents=True, exist_ok=True)
        stage = redact(stage)[:200]
        details = redact(details)[-18000:]
        identifier = hashlib.sha256((stage + '\n' + details).encode('utf-8')).hexdigest()
        path = spool / (identifier + '.json')
        if not path.exists():
            path.write_text(json.dumps({'id': identifier, 'stage': stage, 'details': details,
                                        'python': sys.version.split()[0]}, ensure_ascii=False), encoding='utf-8')
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('issue_url'):
            return 'Отчёт уже отправлен: ' + record['issue_url']
        if not endpoint:
            return 'Отчёт сохранён локально. Автоотправка пока не подключена: нет сервиса приёма журналов.'
        parts = urlsplit(endpoint)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            return 'Отчёт сохранён локально. Адрес сервиса приёма должен использовать HTTPS.'
        request = Request(endpoint, data=json.dumps(record, ensure_ascii=False).encode('utf-8'),
                          headers={'Content-Type': 'application/json', 'User-Agent': 'ResolveDigest/diagnostics'}, method='POST')
        with build_opener(ProxyHandler({})).open(request, timeout=8) as response:
            result = json.loads(response.read(8192).decode('utf-8'))
        issue_url = result.get('issue_url', '')
        if not re.fullmatch(r'https://github\.com/Opragopa/ResolveDigestScript/issues/\d+', issue_url):
            raise ValueError('Invalid issue response')
        record['issue_url'] = issue_url
        path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        return 'Отчёт отправлен в GitHub Issues: ' + issue_url
    except Exception:
        return 'Не удалось отправить отчёт. Используйте локальный журнал; работа программы завершена.'


def retry_pending(directory=None, spool=None):
    """Retry at most one saved report per launch; never delay an unconfigured app."""
    try:
        root = Path(directory) if directory else Path(__file__).resolve().parent.parent
        if not json.loads((root / 'diagnostics.json').read_text(encoding='utf-8')).get('endpoint'):
            return ''
        spool = Path(spool) if spool else Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ResolveDigest' / 'reports'
        for path in sorted(spool.glob('*.json')):
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                if not record.get('issue_url'):
                    return report_diagnostic(record['stage'], record['details'], root, spool)
            except (OSError, ValueError, KeyError):
                continue
    except Exception:
        pass
    return ''
