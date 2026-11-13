import ast
import builtins
import ctypes
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from resolve_digest import fusion
from test_fusion import Composition, articles

ENTRY = Path(__file__).resolve().parents[1] / 'ResolveDigest.py'


def launcher():
    # Load helpers without opening the interactive menu entry point.
    tree = ast.parse(ENTRY.read_text(encoding='utf-8'))
    tree.body.pop()  # final run()
    scope = {'__file__': str(ENTRY), '__name__': 'launcher_test'}
    exec(compile(tree, str(ENTRY), 'exec'), scope)
    scope["_refresh_installation"] = lambda directory: False  # No network in launcher unit tests.
    return scope


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.scope = launcher()

    def test_bootstrap_failure_is_reported_without_composition(self):
        report = MagicMock()
        def fail():
            raise RuntimeError('folder unavailable')
        self.scope.update(_script_directory=fail, _report_error=report)
        self.scope['run']()
        self.assertIsNone(report.call_args.args[0])
        self.assertIn('folder unavailable', str(report.call_args.args[2]))

    def test_import_failure_is_reported(self):
        original = builtins.__import__
        def importing(name, *args, **kwargs):
            if name == 'resolve_digest.downloads':
                raise ImportError('requests missing')
            return original(name, *args, **kwargs)
        report = MagicMock()
        self.scope['_report_error'] = report
        with patch('builtins.__import__', side_effect=importing):
            self.scope['run']()
        self.assertIsInstance(report.call_args.args[2], ImportError)

    def test_no_project_error_is_reported_without_composition(self):
        report = MagicMock()
        self.scope['_report_error'] = report
        with patch.object(fusion, 'current_timeline_composition', side_effect=RuntimeError('no project')):
            self.scope['run']()
        self.assertIsNone(report.call_args.args[0])
        self.assertIn('no project', str(report.call_args.args[2]))

    def test_cancel_does_not_report_error(self):
        report = MagicMock()
        self.scope.update(_ask_options=lambda comp: None, _report_error=report)
        with patch.object(fusion, 'current_timeline_composition', return_value=Composition()):
            self.scope['run']()
        report.assert_not_called()

    def test_error_log_includes_traceback_and_stage(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            message = MagicMock()
            self.scope['_message'] = message
            with patch.dict(os.environ, {'LOCALAPPDATA': folder}):
                try:
                    raise RuntimeError('example failure')
                except RuntimeError as error:
                    self.scope['_report_error'](None, 'startup', error)
            content = (Path(folder) / 'ResolveDigest' / 'ResolveDigest.log').read_text(encoding='utf-8')
            self.assertIn('Traceback', content)
            self.assertIn('Stage: startup', content)
            self.assertIn('example failure', message.call_args.args[2])

    @unittest.skipUnless(os.name == 'nt', 'Windows dialog')
    def test_chooser_error_is_not_treated_as_cancel(self):
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'blocked')):
            with self.assertRaisesRegex(RuntimeError, 'blocked'):
                self.scope['_ask_options'](None)

    @unittest.skipUnless(os.name == 'nt', 'Windows paths')
    def test_menu_without_file_or_fusion_uses_user_scripts(self):
        del self.scope['__file__']
        self.assertEqual(self.scope['_script_directory'](), ENTRY.parent)

    @unittest.skipUnless(os.name == 'nt', 'Win32 ctypes')
    def test_message_centres_on_primary_and_releases_hook(self):
        from ctypes import wintypes as w
        user, kernel = MagicMock(), MagicMock()
        kernel.GetCurrentThreadId.return_value = 123
        user.SetWindowsHookExW.return_value = 456
        user.CallNextHookEx.return_value = 0
        def area(action, unused, pointer, flags):
            rect = ctypes.cast(pointer, ctypes.POINTER(w.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = 0, 40, 1920, 1080
            return 1
        def window(hwnd, pointer):
            rect = ctypes.cast(pointer, ctypes.POINTER(w.RECT)).contents
            # Window starts on a secondary display to the left of the primary.
            rect.left, rect.top, rect.right, rect.bottom = -1600, 100, -1200, 300
            return 1
        def show(*args):
            callback = user.SetWindowsHookExW.call_args.args[1]
            callback(5, 789, 0)
            return 1
        user.SystemParametersInfoW.side_effect = area
        user.GetWindowRect.side_effect = window
        user.MessageBoxW.side_effect = show
        with patch('ctypes.WinDLL', side_effect=[user, kernel]):
            self.scope['_windows_message']('title', 'text')
        self.assertEqual(user.SetWindowPos.call_args.args[2:4], (760, 460))
        user.UnhookWindowsHookEx.assert_called_once_with(456)


class FailureSafetyTests(unittest.TestCase):
    def test_missing_last_node_makes_no_changes(self):
        comp = Composition('image_05')
        with self.assertRaises(fusion.ResolveUpdateError):
            fusion.update_composition(comp, articles())
        self.assertTrue(all(not node.values for node in comp.nodes.values()))

    def test_rejected_write_unlocks_and_closes_undo(self):
        comp = Composition()
        comp.StartUndo, comp.EndUndo = MagicMock(), MagicMock()
        comp.nodes['body_02'].SetInput = MagicMock(return_value=False)
        with self.assertRaises(fusion.ResolveUpdateError):
            fusion.update_composition(comp, articles())
        self.assertFalse(comp.locked)
        comp.EndUndo.assert_called_once_with(True)

    def test_wrong_node_type_is_detected_before_writing(self):
        comp = Composition()
        comp.nodes['image_05'].GetAttrs = lambda: {'TOOLS_RegID': 'MediaIn'}
        with self.assertRaisesRegex(fusion.ResolveUpdateError, 'Loader'):
            fusion.update_composition(comp, articles())
        self.assertTrue(all(not node.values for node in comp.nodes.values()))

    def test_injected_resolve_does_not_import_api(self):
        host = MagicMock()
        try:
            fusion.set_resolve_instance(host)
            with patch.object(fusion, '_resolve_api', side_effect=AssertionError('should not import')):
                self.assertIs(fusion.current_project(), host.GetProjectManager().GetCurrentProject())
        finally:
            fusion.set_resolve_instance(None)
