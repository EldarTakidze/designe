"""Базовая геометрия квартиры: стены из обмерного PDF (мм, ось Y вниз).

Система координат N ("normal"): начало — внутренний угол помещения 4
(левый верхний), X вправо, Y вниз (как на чертеже).
Система R ("rotated"): повернута на ANGLE градусов — в ней стены
диагонального крыла (помещения 6–11) параллельны осям.
"""
import json, math, os
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union
from shapely import affinity

HERE = os.path.dirname(os.path.abspath(__file__))
ANGLE = 43.75
_C, _S = math.cos(math.radians(ANGLE)), math.sin(math.radians(ANGLE))


def r2n(u, v):
    return (u * _C - v * _S, u * _S + v * _C)


def n2r(x, y):
    return (x * _C + y * _S, -x * _S + y * _C)


def to_n(frame, x, y):
    return r2n(x, y) if frame == 'r' else (x, y)


def rect(frame, x0, y0, x1, y1):
    """Прямоугольник, заданный в системе frame, как полигон в N."""
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return Polygon([to_n(frame, *p) for p in pts])


def seg(frame, x0, y0, x1, y1, t=100):
    """Стена-отрезок толщиной t (ось — по отрезку) в системе frame."""
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    nx, ny = -dy / L * t / 2, dx / L * t / 2
    pts = [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]
    return Polygon([to_n(frame, *p) for p in pts])


def load_walls():
    raw = json.load(open(os.path.join(HERE, 'source_walls.json')))
    out = {}
    for k in ('mono', 'gas'):
        tris = [Polygon(p['pts']).buffer(1, join_style=2) for p in raw if p['k'] == k]
        u = unary_union([t for t in tris if t.is_valid and t.area > 0])
        out[k] = u.buffer(-1, join_style=2).simplify(8)
    out['gas'] = out['gas'].difference(out['mono']).simplify(8)
    return out


def polys(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for p in getattr(g, 'geoms', []) if isinstance(p, Polygon) and p.area > 1000]
