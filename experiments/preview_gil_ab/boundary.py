"""Only the protected preview base-call varies. No per-paint observer wrapper."""
from pathlib import Path
import sys


class Boundary:
    def __init__(self,root,mode):
        assert mode in ('original','bridge')
        for name in ('canvas_bridge_semantics','qt_label_valid_paint_control'):
            sys.path.insert(0,str(Path(root)/'experiments'/name))
        from ui.annotation_canvas import AnnotationCanvas
        from bridge import Bridge
        from derive import derive
        self.cls=AnnotationCanvas;self.original=AnnotationCanvas.paintEvent;self.mode=mode
        # Both groups perform the same one-time import/ABI validation/derivation.
        self.bridge=Bridge()
        self.generated,self.source,self.audit=derive(self.original,self.bridge,
            str(Path(__file__).parent/'generated_preview_paint.py'))
        self.installed=self.original if mode=='original' else self.generated

    def start(self):
        assert self.cls.paintEvent is self.original
        self.cls.paintEvent=self.installed

    def close(self):
        intact=self.cls.paintEvent is self.installed
        self.cls.paintEvent=self.original
        return dict(mode=self.mode,installed_intact=intact,restored=self.cls.paintEvent is self.original,AST_audit=self.audit,
            original_method_is_installed=self.installed is self.original,per_paint_safety_wrapper=False)


def verify(record,mode):
    assert record['mode']==mode and record['installed_intact'] and record['restored']
    assert record['AST_audit']['only_first_statement_changed'] and record['AST_audit']['remaining_body_AST_equal']
    assert record['original_method_is_installed']==(mode=='original') and not record['per_paint_safety_wrapper']
