"""Byte-exact baseline/candidate beam pixels, transitions and cache reuse."""
import hashlib,importlib.util,json,math,platform,sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from qtpy.QtWidgets import QApplication
from qtpy.QtGui import QImage
from qtpy import QT_VERSION
from hardware.sensor_frame import DeviceLayout
from ui.ground_track import GroundChannelWidget

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def image_bytes(pixmap):
    img=pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(img.constBits(),np.uint8,count=img.sizeInBytes()).copy(),[img.width(),img.height()]

class Widget(GroundChannelWidget):
    requested_dpr=1
    def devicePixelRatioF(self):return self.requested_dpr

if __name__=='__main__':
    app=QApplication([])
    a=load('golden_beams',HERE/'baseline_renderer.py')
    b=load('candidate_beams',ROOT/'experiments/runtime_single_frame_fusion/fixed_geometry_cache.py')
    rows=[]
    for count in (96,768):
        for dpr in (1,1.25,1.5,2):
            for size in ((221,261),(337,753)):
                for integrated in (False,True):
                    for direction in ('Interface side','Opposite side'):
                        for overview in (False,True):
                            widgets=[Widget(overview=overview),Widget(overview=overview)]
                            for w in widgets:
                                w.requested_dpr=dpr;w.resize(*size);w.setProperty('integrated',integrated);w.set_direction(direction)
                                w._positions_m=DeviceLayout.linear(count//96).positions_m
                            patterns={
                              'empty':([0]*count,[1]*count),
                              'all_active':([1]*count,[1]*count),
                              'continuous':([int(count//3<=i<2*count//3) for i in range(count)],[1]*count),
                              'edges':([int(i<3 or i>=count-3) for i in range(count)],[1]*count),
                              'bad_points':([int(i%3==0) for i in range(count)],[int(i not in (0,1,count//2,count-1)) for i in range(count)]),
                              'alternating':([i%2 for i in range(count)],[int(i%3!=0) for i in range(count)]),
                              'all_bad':([1]*count,[0]*count),
                              'short_valid':([int(i%2==0) for i in range(count)],[1]*(count-3)),
                              'empty_again':([0]*count,[1]*count),
                            }
                            for name,(bits,valid) in patterns.items():
                                for w in widgets:w._contact_bits=bits;w.valid_bits=valid
                                images=[];dimensions=[]
                                for module,w in zip((a,b),widgets):
                                    g=module.geometry(w);pixmap=module.beam_layer(w,g)
                                    assert pixmap is module.beam_layer(w,g),'Cache-hit object changed'
                                    assert pixmap.devicePixelRatioF()==dpr
                                    data,shape=image_bytes(pixmap)
                                    assert shape==[math.ceil(w.width()*dpr),math.ceil(w.height()*dpr)]
                                    images.append(data);dimensions.append(shape)
                                assert dimensions[0]==dimensions[1] and np.array_equal(*images),(count,dpr,size,integrated,direction,overview,name)
                                rows.append({'beams':count,'DPR':dpr,'size':size,'integrated':integrated,'direction':direction,'overview':overview,'pattern':name,'physical_pixels':dimensions[0],'rgba_sha256':hashlib.sha256(images[0]).hexdigest(),'mismatched_bytes':0})
                            for w in widgets:w.close();w.deleteLater()
    result={'cases':len(rows),'all_pixels_exact':True,'scope':'RGBA pixels of independently created pixmaps, including overlapping 768-beam markers; state transitions reuse widgets and repeat empty. No image tolerance, performance inference or draw reordering. Each DPR is explicitly attached to physical pixmap dimensions.','python':sys.version,'platform':platform.platform(),'qt':QT_VERSION,'baseline_sha256':hashlib.sha256((HERE/'baseline_renderer.py').read_bytes()).hexdigest(),'candidate_sha256':hashlib.sha256((ROOT/'experiments/runtime_single_frame_fusion/fixed_geometry_cache.py').read_bytes()).hexdigest(),'rows':rows}
    output=HERE/('pixels_windows.json' if sys.platform=='win32' else 'pixels_mac.json')
    output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='rows'}),flush=True)
