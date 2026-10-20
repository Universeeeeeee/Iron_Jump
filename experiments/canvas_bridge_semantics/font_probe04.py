"""Check actual glyph outlines and raster delivery from existing OS fonts."""
import hashlib
import json
import os
from pathlib import Path


def delivery(app,output):
    from PySide6 import QtGui
    output=Path(output)
    assert Path(os.environ.get('QT_QPA_FONTDIR','')).resolve()==(Path(__file__).resolve().parent/'font_fixture04').resolve()
    manifest=json.loads((Path(__file__).parent/'font_fixture04.json').read_text())
    assert all(hashlib.sha256(Path(v['copy']).read_bytes()).hexdigest()==v['sha256'] for v in manifest['files'])
    font=QtGui.QFont(app.font());font.setPixelSize(28)
    text='未连接相机LR第1–3帧0.200s（估算）°'
    layout=QtGui.QTextLayout(text,font);layout.beginLayout();line=layout.createLine();assert line.isValid()
    line.setLineWidth(2000);layout.endLayout();runs=[]
    for run in layout.glyphRuns():
        raw=run.rawFont();indices=list(run.glyphIndexes())
        assert raw.isValid() and indices and all(i>0 for i in indices)
        outlines=sum(not raw.pathForGlyph(i).isEmpty() for i in indices)
        assert outlines==len(indices)
        runs.append(dict(family=raw.familyName(),glyph_indices=indices,nonempty_outlines=outlines))
    assert runs
    pixels=[];rasters=[]
    for name,label in [('left','左脚'),('right','右脚')]:
        image=QtGui.QImage(600,120,QtGui.QImage.Format_ARGB32_Premultiplied);image.fill(0xff010203)
        before=bytes(image.constBits());painter=QtGui.QPainter(image);painter.setFont(font)
        painter.setPen(QtGui.QColor('white'));painter.drawText(12,70,label);painter.end()
        raw=bytes(image.constBits());assert raw!=before
        with (output/f'font_{name}.argb').open('xb') as f:f.write(raw)
        assert image.save(str(output/f'font_{name}.png'))
        pixels.append(raw);rasters.append(dict(text=label,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)))
    assert pixels[0]!=pixels[1]
    return dict(font_delivery_pass=True,default_font=app.font().toString(),probe_font=font.toString(),glyph_runs=runs,rasters=rasters,
        existing_font_directory_only=True,system_or_project_fonts_modified=False)


if __name__=='__main__':
    from PySide6 import QtCore,QtWidgets
    here=Path(__file__).resolve().parent;output=here/'font_preflight04';output.mkdir()
    result=dict(errors=[],Qt_messages=[],handler_restored=False,font_delivery_pass=False)
    app=QtWidgets.QApplication([])
    def handler(kind,context,message):result['Qt_messages'].append(dict(kind=str(kind),message=message))
    previous=QtCore.qInstallMessageHandler(handler)
    try:result.update(delivery(app,output))
    except Exception as exc:result['errors'].append(repr(exc))
    finally:result['handler_restored']=QtCore.qInstallMessageHandler(previous) is handler
    result['passed']=result['font_delivery_pass'] and not result['errors'] and not result['Qt_messages'] and result['handler_restored']
    result['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with (here/'font_preflight04.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 2)
