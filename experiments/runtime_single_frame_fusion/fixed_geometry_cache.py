"""Isolated candidate: geometry and one beam-state pixmap per ground widget."""
import math
from qtpy.QtCore import QLineF,QRectF,Qt
from qtpy.QtGui import QBrush,QColor,QPainter,QPixmap
from qtpy.QtWidgets import QFrame
from ui.footprint_channel import FootprintChannelWidget
from ui.ground_track import GroundChannelWidget

ORIGINAL=FootprintChannelWidget.paintEvent

def geometry(widget):
    positions=tuple(widget._positions_m or ())
    key=(widget.width(),widget.height(),widget.devicePixelRatioF(),widget._direction,positions,len(widget._contact_bits))
    cached=getattr(widget,'_isolated_geometry',None)
    if cached and cached[0]==key:return cached
    rect=widget.rect().adjusted(14,14,-14,-14);left=rect.left()+12;right=rect.right()-12
    lane=widget.lane_rect();top,height=int(lane.top()),int(lane.height())
    ys=[widget._y_for_index(i,top,height) for i in range(len(widget._contact_bits))]
    marker_height=min(6.0,max(2.0,height/(len(ys)-1)*.78))
    left_rects=[QRectF(left-3.,y-marker_height/2.,6.,marker_height) for y in ys]
    right_rects=[QRectF(right-3.,y-marker_height/2.,6.,marker_height) for y in ys]
    cached=(key,left,right,lane,top,height,ys,left_rects,right_rects)
    widget._isolated_geometry=cached
    widget._isolated_geometry_builds=getattr(widget,'_isolated_geometry_builds',0)+1
    return cached

def beam_layer(widget,g):
    key=(g[0],bool(widget.property('integrated')),tuple(widget._contact_bits),tuple(widget.valid_bits))
    cached=getattr(widget,'_isolated_beams',None)
    if cached and cached[0]==key:return cached[1]
    dpr=g[0][2];pixmap=QPixmap(math.ceil(widget.width()*dpr),math.ceil(widget.height()*dpr));pixmap.setDevicePixelRatio(dpr);pixmap.fill(Qt.transparent)
    p=QPainter(pixmap);p.setRenderHint(QPainter.Antialiasing);p.setRenderHint(QPainter.SmoothPixmapTransform)
    _,left,right,lane,top,height,ys,left_rects,right_rects=g
    lane_left,lane_right=int(lane.left()),int(lane.right())
    integrated=bool(widget.property('integrated'))
    p.setPen(Qt.NoPen if integrated else QColor(70,70,76))
    p.setBrush(QColor(255,255,255,5) if integrated else QColor(28,28,32))
    p.drawRoundedRect(lane_left,top,lane_right-lane_left,height,8,8)
    p.setPen(Qt.NoPen);p.setBrush(QColor(42,42,48))
    p.drawRoundedRect(QRectF(left-3.,top-2.,6.,height+4.),3.,3.)
    p.drawRoundedRect(QRectF(right-3.,top-2.,6.,height+4.),3.,3.)
    brushes=(QBrush(QColor('#ddaa57')),QBrush(QColor(70,220,125)),QBrush(QColor(70,70,76)))
    line_colour=QColor(70,220,125,60)
    brush_state=None
    # Preserve original per-beam ordering: markers may overlap at 768-beam density.
    for i,active in enumerate(widget._contact_bits):
        valid=i<len(widget.valid_bits) and widget.valid_bits[i]
        state=0 if not valid else 1 if active else 2
        if state!=brush_state:
            p.setBrush(brushes[state]);brush_state=state
        p.drawRoundedRect(left_rects[i],2.,2.);p.drawRoundedRect(right_rects[i],2.,2.)
        if active and valid:
            p.setPen(line_colour);p.drawLine(QLineF(float(lane_left),ys[i],float(lane_right),ys[i]))
            p.setPen(Qt.NoPen)
    p.end();widget._isolated_beams=(key,pixmap)
    widget._isolated_beam_builds=getattr(widget,'_isolated_beam_builds',0)+1
    return pixmap

def cached_paint(widget,event):
    if not isinstance(widget,GroundChannelWidget) or not widget._positions_m or len(widget._contact_bits)<2:
        return ORIGINAL(widget,event)
    QFrame.paintEvent(widget,event)
    g=geometry(widget);layer=beam_layer(widget,g)
    p=QPainter(widget);p.setRenderHint(QPainter.Antialiasing);p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.drawPixmap(0,0,layer)
    lane=g[3];top,height=g[4:6];left,right=int(lane.left()),int(lane.right())
    p.save()
    if widget._positions_m:p.setClipRect(lane)
    p.setOpacity(.32)
    for foot in widget.history:widget._paint_foot(p,foot,left,right,top,height)
    p.setOpacity(1)
    if len(widget.valid_bits)==len(widget._contact_bits) and any(widget.valid_bits):
        for foot in widget._feet:
            centre,length=foot.get('centroid_cm'),foot.get('length_cm')
            if centre is not None and foot.get('shape_valid') is False:
                widget._paint_foot(p,foot,left,right,top,height)
                continue
            if centre is None or length is None:continue
            overlaps=any(not valid and abs(position*100-centre)<=length/2+1.04 for position,valid in zip(widget._positions_m,widget.valid_bits))
            if not overlaps:widget._paint_foot(p,foot,left,right,top,height)
    p.restore();p.end()

def install():
    if FootprintChannelWidget.paintEvent is not ORIGINAL:raise RuntimeError('Install candidate before diagnostic paint wrappers')
    FootprintChannelWidget.paintEvent=cached_paint

def restore():FootprintChannelWidget.paintEvent=ORIGINAL
