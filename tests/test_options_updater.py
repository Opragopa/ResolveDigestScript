import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from resolve_digest.options import load_preferences, ask_windows_options
from resolve_digest.updater import update_checkout


class PreferenceTests(unittest.TestCase):
    def test_defaults_and_saved_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(load_preferences(folder)['body_gap_pixels'],80)
            p=Path(folder)/'resolve_digest.local.json'
            p.write_text(json.dumps({'body_gap_pixels':140,'auto_update':False}),encoding='utf-8')
            self.assertEqual(load_preferences(folder)['body_gap_pixels'],140)
            self.assertFalse(load_preferences(folder)['auto_update'])

    def test_cancel_keeps_existing_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'resolve_digest.local.json'
            path.write_text('{"body_gap_pixels": 140}',encoding='utf-8')
            with patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')):
                self.assertIsNone(ask_windows_options(folder))
            self.assertEqual(load_preferences(folder)['body_gap_pixels'],140)

    def test_manual_check_preserves_options_without_persisting_action(self):
        with tempfile.TemporaryDirectory() as folder:
            values = {'action': 'check_updates', 'docx': '', 'body_gap_pixels': 120, 'auto_update': False}
            with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps(values), '')):
                options = ask_windows_options(folder)
            self.assertEqual(options['action'], 'check_updates')
            saved = load_preferences(folder)
            self.assertNotIn('action', saved)
            self.assertEqual(saved['body_gap_pixels'], 120)
            self.assertFalse(saved['auto_update'])


class UpdaterTests(unittest.TestCase):
    def result(self,text='',code=0):
        return subprocess.CompletedProcess([],code,text,'failure' if code else '')

    def test_dirty_checkout_checks_remote_without_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            responses=[str(Path(folder).resolve()),'main','https://github.com/Opragopa/ResolveDigestScript',
                       'aaa','','bbb',' M ResolveDigest.py']
            with patch('subprocess.run',side_effect=[self.result(r) for r in responses]) as run:
                updated,message=update_checkout(folder)
            self.assertFalse(updated)
            self.assertIn('локальные',message)
            self.assertIn('bbb', message)
            self.assertTrue(any('fetch' in c.args[0] for c in run.call_args_list))
            self.assertFalse(any('merge' in c.args[0] for c in run.call_args_list))

    def test_clean_update_is_fast_forward_only(self):
        with tempfile.TemporaryDirectory() as folder:
            responses=[str(Path(folder).resolve()),'main','https://github.com/Opragopa/ResolveDigestScript','aaa','','bbb','','','bbb']
            with patch('subprocess.run',side_effect=[self.result(r) for r in responses]) as run:
                updated,message=update_checkout(folder)
            self.assertTrue(updated)
            commands=[c.args[0] for c in run.call_args_list]
            self.assertTrue(any('--ff-only' in c for c in commands))
            self.assertFalse(any('reset' in c for c in commands))

    def test_current_version_is_reported_without_merge(self):
        with tempfile.TemporaryDirectory() as folder:
            responses = [str(Path(folder).resolve()), 'main', 'https://github.com/Opragopa/ResolveDigestScript',
                         'aaa', '', 'aaa']
            with patch('subprocess.run', side_effect=[self.result(r) for r in responses]) as run:
                updated, message = update_checkout(folder)
            self.assertFalse(updated)
            self.assertIn('последняя версия', message)
            self.assertFalse(any('merge' in c.args[0] for c in run.call_args_list))

    def test_offline_update_preserves_installed_version(self):
        with patch('subprocess.run',side_effect=OSError('offline')):
            updated,message=update_checkout('.')
        self.assertFalse(updated)
        self.assertIn('установленная',message)

class LayoutOnlyWorkflowTests(unittest.TestCase):
    def test_manual_check_forces_refresh_and_reopens_options(self):
        from test_startup import launcher
        from test_fusion import Composition
        from resolve_digest import fusion
        from unittest.mock import MagicMock
        scope = launcher()
        refresh = MagicMock(return_value=False)
        options = MagicMock(side_effect=[{'action': 'check_updates', 'auto_update': False}, None])
        scope.update(_refresh_installation=refresh, _ask_options=options, _report_error=MagicMock())
        with patch.object(fusion, 'current_timeline_composition', return_value=Composition()), \
             patch.object(fusion, 'update_composition') as update:
            scope['run']()
        self.assertEqual(options.call_count, 2)
        self.assertEqual(refresh.call_count, 2)
        self.assertTrue(refresh.call_args.kwargs['force'])
        update.assert_not_called()
        scope['_report_error'].assert_not_called()

    def test_layout_only_uses_saved_gap_without_docx_or_network(self):
        from test_startup import launcher
        from test_fusion import Composition
        from resolve_digest import fusion
        from unittest.mock import MagicMock
        scope=launcher()
        progress=MagicMock()
        scope['_ask_options']=lambda comp:{'layout_only':True,'body_gap_pixels':140}
        scope['_report_error']=MagicMock()
        with patch('resolve_digest.progress.create_progress',return_value=progress), \
             patch.object(fusion,'current_timeline_composition',return_value=Composition()), \
             patch.object(fusion,'reflow_composition') as reflow, \
             patch('resolve_digest.article_images.download_all_article_images') as download, \
             patch('resolve_digest.docx_parser.parse_docx') as parse:
            scope['run']()
        reflow.assert_called_once()
        self.assertEqual(reflow.call_args.args[1],140)
        download.assert_not_called()
        parse.assert_not_called()
        self.assertEqual(progress.finish.call_args.args[0],'success')
        scope['_report_error'].assert_not_called()


class BootstrapUpdateTests(unittest.TestCase):
    def test_downloaded_launcher_is_executed_once_with_original_host(self):
        import ast,builtins,sys
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from test_startup import launcher,ENTRY
        scope=launcher()
        tree=ast.parse(ENTRY.read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_refresh_installation')
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(ENTRY),'exec'),scope)
        original_import=builtins.__import__
        update=MagicMock(return_value=(True,'new version'))
        def importing(name,*args,**kwargs):
            if name=='resolve_digest.options':
                return SimpleNamespace(load_preferences=lambda directory:{'auto_update':True})
            if name=='resolve_digest.updater':
                return SimpleNamespace(update_checkout=update)
            return original_import(name,*args,**kwargs)
        saved={name:module for name,module in sys.modules.items() if name=='resolve_digest' or name.startswith('resolve_digest.')}
        try:
            with tempfile.TemporaryDirectory() as folder:
                (Path(folder)/'ResolveDigest.py').write_text("assert _DIGEST_SKIP_UPDATE\nresolve.append('new code')\n",encoding='utf-8')
                host=[]
                scope['resolve']=host
                with patch('builtins.__import__',side_effect=importing):
                    self.assertTrue(scope['_refresh_installation'](folder))
                self.assertEqual(host,['new code'])
                update.assert_called_once()
        finally:
            sys.modules.update(saved)
