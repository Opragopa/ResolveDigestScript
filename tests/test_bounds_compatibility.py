import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from resolve_digest.fusion import _text_bounds, _components, photo_vertical_limits, reflow_composition, PHOTO_BRANCHES, ResolveUpdateError
from test_photo_layout import photo_comp


class BoundsCompatibilityTests(unittest.TestCase):
    def test_photo_uses_rendered_datawindow_when_getdod_returns_none(self):
        comp=photo_comp()
        output=comp.nodes[PHOTO_BRANCHES[0][0]].Output
        output.GetValue=MagicMock(return_value=SimpleNamespace(
            Height=2160,DataWindow={0:0,1:400,2:1800,3:1900}))
        output.GetDoD=MagicMock(return_value=None)
        self.assertEqual(photo_vertical_limits(comp,1,2160),(400,1900))
        output.GetDoD.assert_not_called()
        output.GetValue.assert_called_once()

    def test_text_renders_as_fallback_when_getdod_returns_none(self):
        output=SimpleNamespace(GetDoD=lambda *args:None,
            GetValue=lambda *args:SimpleNamespace(DataWindow={1:100,2:200,3:400,4:500}))
        self.assertEqual(_text_bounds(SimpleNamespace(Output=output),14),[100,200,400,500])

    def test_getdod_default_signature_is_supported(self):
        def dod(frame):
            return [100,200,400,500]
        self.assertEqual(_text_bounds(SimpleNamespace(Output=SimpleNamespace(GetDoD=dod)),14),[100,200,400,500])

    def test_getvalue_default_signature_is_supported(self):
        def image(frame):
            return SimpleNamespace(DataWindow=[100,200,400,500])
        self.assertEqual(_text_bounds(SimpleNamespace(Output=SimpleNamespace(GetValue=image)),14),[100,200,400,500])

    def test_named_rectangle_coordinates_are_supported(self):
        self.assertEqual(_components({'left':100,'bottom':200,'right':400,'top':500},4),[100,200,400,500])
        self.assertEqual(_components({'x1':100,'y1':200,'x2':400,'y2':500},4),[100,200,400,500])

    def test_native_rect_wrapper_is_supported(self):
        self.assertEqual(_components(SimpleNamespace(left=100,bottom=200,right=400,top=500),4),[100,200,400,500])
        self.assertEqual(_components(SimpleNamespace(X=.75,Y=.335),2),[.75,.335])

    def test_missing_bounds_report_node_frame_and_actual_api_results(self):
        tool=SimpleNamespace(Output=SimpleNamespace(GetDoD=lambda *args:None,
            GetValue=lambda *args:SimpleNamespace(DataWindow=None)))
        with self.assertRaises(ResolveUpdateError) as caught:
            _text_bounds(tool,14,label='body_03')
        message=str(caught.exception)
        self.assertIn('body_03',message)
        self.assertIn('14',message)
        self.assertIn('NoneType',message)
        self.assertIn('DataWindow',message)

    def test_complete_reflow_with_none_getdod(self):
        comp=photo_comp()
        for index in range(1,6):
            static=comp.nodes[PHOTO_BRANCHES[index-1][0]]
            static.Output.GetValue=lambda *args:SimpleNamespace(Height=2160,DataWindow=[0,400,1800,1900])
            static.Output.GetDoD=lambda *args:None
            for kind in ('title','body'):
                node=comp.nodes[f'{kind}_{index:02d}']
                old_bounds=node.Output.GetDoD
                node.Output.GetValue=lambda *args,old=old_bounds:SimpleNamespace(DataWindow=old(14))
                node.Output.GetDoD=lambda *args:None
            title,body=comp.nodes[f'title_{index:02d}'],comp.nodes[f'body_{index:02d}']
            def install(expression,title=title,body=body,index=index):
                title.Output.DataWindow={2:title.Output.GetValue(14).DataWindow[1]}
                x,y=eval(expression,{'Point':lambda x,y:(x,y),f'title_{index:02d}':title, f'body_{index:02d}':body})
                body.values['Center']={1:x,2:y}
            body.Center.SetExpression.side_effect=install
        reflow_composition(comp,100)
        for i in range(1,6):
            comp.nodes[f'body_{i:02d}'].Center.SetExpression.assert_called_once()
