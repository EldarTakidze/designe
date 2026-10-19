"""Проект планировки: перепланировка, двери, помещения и мебель.

Все размеры в описаниях ниже — в МЕТРАХ в своей системе координат
('n' — как на обмерном плане, 'r' — повёрнутая система крыла),
при сборке переводятся в мм системы N (см. geom.py).
"""
import json, math, os, sys
import numpy as np
import cv2
from shapely.geometry import Polygon, LineString, Point, mapping
from shapely.ops import unary_union
import ergonomics
from geom import load_walls, rect, seg, polys, to_n, r2n, n2r, HERE

M = 1000.0
CEIL = 3262

# --- Окна (из обмеров): система, ось вдоль, координата поперёк, от, до -------
WINDOWS = [
    # (frame, along_from, along_to, across, high)  across = линия окна
    dict(id='W1', frame='n', a0=0.502, a1=2.629, c=-0.255, axis='x', h=2935),
    dict(id='W2', frame='n', a0=3.833, a1=5.915, c=-0.245, axis='x', h=2935),
    dict(id='W3', frame='n', a0=7.125, a1=9.206, c=-0.240, axis='x', h=2935),
    dict(id='W4', frame='r', a0=7.620, a1=9.720, c=-6.905, axis='x', h=2956),
    dict(id='W5', frame='r', a0=10.918, a1=13.000, c=-6.92, axis='x', h=2938),
    dict(id='W6', frame='r', a0=14.390, a1=16.290, c=-6.93, axis='x', h=2935),
]
RISERS = [(172, 3895), (9304, 4455), (7579, 6644), (8795, 8333), (12308, 11119)]
ENTRANCE = dict(frame='n', x0=4.44, x1=5.54, y=6.98)
EL_PANEL = dict(frame='n', x0=5.63, y0=6.46, x1=5.76, y1=6.76)


def mm_rect(frame, x0, y0, x1, y1):
    return rect(frame, x0 * M, y0 * M, x1 * M, y1 * M)


def mm_seg(frame, x0, y0, x1, y1, t=0.1):
    return seg(frame, x0 * M, y0 * M, x1 * M, y1 * M, t * M)


class Variant:
    def __init__(self, vid, title, summary):
        self.id, self.title, self.summary = vid, title, summary
        self.demolish, self.new_walls, self.doors, self.rooms = [], [], [], []
        self.furniture, self.notes = [], []

    # перепланировка
    def demo(self, frame, x0, y0, x1, y1):
        self.demolish.append(mm_rect(frame, x0, y0, x1, y1))

    def wall(self, frame, x0, y0, x1, y1, t=0.1, kind='new'):
        """kind: new — газобетон/ПГП 100, gkl — гипрокартон."""
        self.new_walls.append((mm_seg(frame, x0, y0, x1, y1, t), kind))

    def door(self, frame, x0, y0, x1, y1, kind='swing', hinge=0, side=1, t=0.45, h=2.1):
        """Проём по оси стены (x0,y0)-(x1,y1). kind: swing|slide|open|mirror.
        hinge: 0/1 — у какого конца петли; side: ±1 — куда открывается
        (по левой нормали к направлению оси)."""
        self.doors.append(dict(frame=frame, p0=(x0, y0), p1=(x1, y1), kind=kind,
                               hinge=hinge, side=side, t=t, h=h))

    def room(self, name, frame, x, y, floor, who=''):
        self.rooms.append(dict(name=name, seed=to_n(frame, x * M, y * M), floor=floor, who=who))

    def f(self, frame, x0, y0, x1, y1, typ, label='', h=0.75, color=None, back='n', z=0.0, extra=None):
        """Мебель: прямоугольник в системе frame; back — сторона «спинки»
        (n/s/w/e по осям системы: n — к меньшему y)."""
        self.furniture.append(dict(frame=frame, x0=x0, y0=y0, x1=x1, y1=y1, type=typ,
                                   label=label, h=h, color=color, back=back, z=z,
                                   extra=extra or {}))

    def note(self, where, text):
        self.notes.append(dict(where=where, text=text))


# ============================================================================
#  Общее для вариантов
# ============================================================================

def common_left(v, hall_closet=True):
    """Левая часть: комнаты 4 и 5, ванна 3, гардеробная 3 (пом. 2), прихожая."""
    # --- Ванна 3 (пом. 3): ванна, раковина, унитаз с инсталляцией, шкафы ---
    v.room('Ванна 3', 'n', 1.0, 5.4, 'tile', 'ванна, раковина, унитаз')
    v.f('n', 0.00, 4.17, 0.25, 4.95, 'install', 'инсталляция', h=1.2)
    v.f('n', 0.00, 4.25, 0.60, 4.85, 'wc', 'унитаз', h=0.4, back='w')
    v.f('n', 0.00, 4.95, 0.45, 5.85, 'vanity', 'раковина', h=0.85, back='w')
    v.f('n', 0.00, 4.95, 0.15, 5.85, 'mirror', '', h=0.9, z=1.0)
    v.f('n', 0.00, 6.17, 1.92, 6.92, 'bath', 'ванна 1700×750, поручень', h=0.58, back='s')
    v.f('n', 1.50, 4.75, 1.92, 6.05, 'cabinet', 'шкаф хранения', h=2.2, back='e')
    v.f('n', 0.45, 3.73, 1.92, 3.98, 'shelf', 'ниша над инсталляцией', h=1.2, back='n')

    # --- Гардеробная 3 (пом. 2): полки под потолок, плечики, обувь ---
    v.room('Гардеробная 3', 'n', 3.1, 5.6, 'wood', 'верхняя одежда всей семьи')
    v.f('n', 2.01, 4.93, 4.18, 5.53, 'closet', 'полки до потолка · плечики · обувь внизу', h=3.0, back='n',
        extra=dict(tiers=True))
    v.f('n', 2.01, 6.26, 4.18, 6.41, 'hooks', 'крючки на детской высоте, сумки', h=1.6, back='s')

    # --- Прихожая ---
    v.room('Прихожая и холл', 'n', 5.0, 5.9, 'stone', 'шкаф, пуф, зеркало')
    if hall_closet:
        v.f('n', 5.90, 4.98, 6.52, 6.30, 'closet', 'шкаф до потолка', h=3.0, back='e')
    else:
        v.f('n', 6.17, 5.95, 6.52, 6.30, 'shoe', 'обувница', h=1.0, back='e')
        v.f('n', 6.17, 4.95, 6.52, 5.02, 'none')
    v.f('n', 4.30, 5.55, 4.70, 6.38, 'bench', 'пуф-скамья с ящиком', h=0.45, back='w')
    v.f('n', 5.82, 6.40, 5.88, 6.90, 'mirror', 'зеркало в рост', h=1.9, z=0.1, back='e')

    # --- существующие проёмы левой части ---
    v.door('n', 2.20, 3.69, 3.05, 3.69, hinge=0, side=-1)    # пом. 4
    v.door('n', 3.36, 3.69, 4.24, 3.69, hinge=0, side=-1)    # пом. 5
    v.door('n', 1.96, 3.95, 1.96, 4.68, hinge=1, side=-1)    # ванна 3
    v.door('n', 4.22, 5.05, 4.22, 5.83, kind='slide')        # гардеробная 3


def girl_room_4(v, name, who):
    """Пом. 4: x 0…3.22, y 0…3.65, окно сверху, дверь внизу x 2.20…3.05.
    Кровать длинной стороной к наружной стене, шкаф напротив — проход 1,4 м."""
    v.room(name, 'n', 1.9, 1.9, 'wood', who)
    v.f('n', 0.00, 1.60, 1.20, 3.60, 'bed', 'кровать 1200×2000', h=0.5, back='s', extra=dict(w=1.2))
    v.f('n', 1.25, 3.20, 2.15, 3.65, 'dresser', 'комод у изголовья', h=0.85, back='s')
    v.f('n', 2.62, 0.75, 3.22, 2.75, 'wardrobe', 'шкаф 2,0 м', h=2.6, back='e')
    v.f('n', 0.10, 0.05, 1.70, 0.65, 'desk', 'рабочий стол у окна', h=0.75, back='n')
    v.f('n', 0.65, 0.75, 1.10, 1.15, 'chair', '', h=0.9, back='s')
    v.f('n', 1.80, 0.05, 2.60, 0.50, 'vanity_table', 'косм. столик', h=0.75, back='n')
    v.f('n', 2.02, 0.60, 2.37, 0.95, 'stool', '', h=0.45)


def girl_room_5(v, name, who):
    """Пом. 5: x 3.29…6.52 (колонна 6.40…6.52 при y 1.8…3.0), окно сверху,
    дверь внизу x 3.36…4.24. Кровать вдоль стены 5/6, к ней подход 1,3 м."""
    v.room(name, 'n', 4.55, 2.0, 'wood', who)
    v.f('n', 5.20, 1.40, 6.40, 3.40, 'bed', 'кровать 1200×2000', h=0.5, back='n', extra=dict(w=1.2))
    v.f('n', 5.95, 0.95, 6.40, 1.38, 'nightstand', 'тумба', h=0.5, back='n')
    v.f('n', 3.29, 0.70, 3.89, 2.70, 'wardrobe', 'шкаф 2,0 м', h=2.6, back='w')
    v.f('n', 3.95, 0.05, 5.05, 0.65, 'desk', 'рабочий стол у окна', h=0.75, back='n')
    v.f('n', 4.30, 0.75, 4.75, 1.15, 'chair', '', h=0.9, back='s')
    v.f('n', 4.40, 3.22, 5.15, 3.65, 'dresser', 'комод', h=0.85, back='s')
    v.f('n', 5.15, 0.05, 5.95, 0.50, 'vanity_table', 'косм. столик', h=0.75, back='n')
    v.f('n', 5.37, 0.55, 5.72, 0.90, 'stool', '', h=0.45)


def wing(v):
    """Крыло: детская (7), мастер-блок (8 + 9 + 10), ванная 2 (11), гардеробная 2 (12)."""
    # ---------------- Детская (пом. 7): u 10.28…13.62, v -6.72…-2.99 -------
    # Угловая кровать-чердак: два верхних места буквой Г, под одним — шкаф
    # на 3 секции, под другим — нижняя кровать (Нико).
    v.room('Детская', 'r', 11.6, -4.6, 'wood', 'Гио, Лео, Нико')
    v.f('r', 10.75, -6.72, 12.65, -6.17, 'desk', 'стол на двоих 1,9 м', h=0.75, back='n')
    v.f('r', 11.05, -6.05, 11.50, -5.60, 'chair', '', h=0.9, back='s')
    v.f('r', 11.90, -6.05, 12.35, -5.60, 'chair', '', h=0.9, back='s')
    v.f('r', 12.70, -6.65, 13.62, -4.65, 'loft', 'верх: Гио', h=1.75, back='e', extra=dict(under='bed'))
    v.f('r', 12.72, -6.63, 13.60, -4.67, 'bed', 'низ: Нико 900×2000', h=0.42, back='n', extra=dict(w=0.9, low=True))
    v.f('r', 11.62, -3.91, 13.62, -2.99, 'loft', 'верх: Лео', h=1.75, back='s', extra=dict(under='wardrobe'))
    v.f('r', 11.64, -3.61, 13.60, -2.99, 'wardrobe', 'шкаф 3 секции под кроватью', h=1.3, back='s',
        extra=dict(sections=3))
    v.f('r', 10.28, -5.95, 10.68, -4.30, 'toys', 'шкафчики для игрушек', h=0.9, back='w')
    v.f('r', 10.28, -6.72, 10.70, -6.05, 'shelf', 'книги', h=1.8, back='w')
    v.f('r', 10.95, -5.35, 12.45, -4.15, 'rug', 'игровая зона', h=0.01)

    # ---------------- Коридор крыла ----------------------------------------
    v.door('r', 10.40, -3.03, 11.40, -3.03, hinge=0, side=1)   # детская
    v.door('r', 12.52, -1.84, 13.40, -1.84, hinge=1, side=-1)  # ванная 2
    v.room('Коридор', 'r', 11.5, -2.4, 'stone', '')

    # ---------------- Мастер-блок ------------------------------------------
    # Перегородка 8/9 переносится на v = -1.90; гардероб-проход 1,4 м и санузел.
    v.demo('r', 14.70, -2.40, 16.80, -2.24)          # старая перегородка 8/9
    v.demo('r', 14.00, -0.20, 16.36, 0.02)           # старая перегородка 9/10
    v.wall('r', 13.66, -1.90, 16.79, -1.90, t=0.10, kind='gkl')   # спальня | гардероб+санузел
    v.wall('r', 15.10, -1.85, 15.10, 2.47, t=0.10, kind='gkl')    # гардероб | санузел
    v.door('r', 14.32, -1.90, 15.05, -1.90, kind='mirror')           # ездящее зеркало
    v.door('r', 15.10, -1.80, 15.10, -1.05, kind='slide')           # в санузел
    v.door('r', 13.66, -2.86, 13.66, -2.01, kind='swing', hinge=1, side=-1)  # из коридора

    v.room('Мастер-спальня', 'r', 15.2, -4.6, 'wood', 'Вы с женой')
    v.f('r', 14.80, -5.30, 16.79, -3.50, 'bed', 'кровать 1800×2000 с подъёмным мех.', h=0.5,
        back='e', extra=dict(w=1.8))
    v.f('r', 16.35, -5.80, 16.79, -5.35, 'nightstand', 'подвесная', h=0.3, z=0.35, back='e')
    v.f('r', 16.35, -3.45, 16.79, -3.00, 'nightstand', 'подвесная', h=0.3, z=0.35, back='e')
    v.f('r', 16.74, -6.00, 16.79, -2.80, 'accent', 'акцентная стена', h=2.9)
    v.f('r', 13.70, -4.75, 14.10, -3.35, 'dresser', 'комод 0,4 + ТВ над ним', h=0.85, back='w')
    v.f('r', 13.70, -4.60, 13.76, -3.50, 'tv', 'ТВ', h=0.7, z=1.25, back='w')
    v.f('r', 13.70, -6.72, 14.30, -5.30, 'desk', 'рабочее место', h=0.75, back='w')
    v.f('r', 14.35, -6.20, 14.80, -5.75, 'chair', '', h=0.9, back='e')
    v.f('r', 15.15, -2.50, 16.79, -1.95, 'wardrobe', 'встроенный шкаф-купе', h=2.7, back='s',
        extra=dict(sliding=True))

    v.room('Гардеробная', 'r', 14.4, 0.6, 'wood', 'полки и штанги до потолка')
    v.f('r', 13.70, -1.85, 14.30, 2.47, 'closet', 'штанги + полки до потолка', h=3.0, back='w')
    v.f('r', 14.30, 1.95, 15.05, 2.47, 'closet', 'полки', h=3.0, back='s')
    v.f('r', 14.42, -1.85, 15.05, -1.65, 'none')

    v.room('Мастер-санузел', 'r', 15.95, 0.9, 'tile', 'душ, унитаз, раковина')
    v.f('r', 16.34, -0.15, 16.79, 0.75, 'install', 'инсталляция', h=1.2)
    v.f('r', 16.19, 0.00, 16.79, 0.60, 'wc', 'унитаз', h=0.4, back='e')
    v.f('r', 15.15, 1.40, 16.79, 2.47, 'shower', 'душ, стеклоблоки', h=2.1,
        extra=dict(glass='blocks', side='n'))
    v.f('r', 15.15, -0.95, 15.60, -0.05, 'vanity', 'раковина + хранение', h=0.85, back='w')
    v.f('r', 15.15, -0.90, 15.20, -0.10, 'mirror_round', 'круглое зеркало с подсветкой', h=0.8, z=1.1, back='w')
    v.f('r', 15.15, 0.70, 15.60, 1.35, 'cabinet', 'шкаф: косметика, подсветка', h=2.2, back='w')
    v.f('r', 16.30, -1.85, 16.79, -0.95, 'cabinet', 'хранение', h=2.2, back='e')

    # ---------------- Ванная 2 (пом. 11) ------------------------------------
    v.room('Ванная 2', 'r', 12.8, 0.5, 'tile', 'душ, стиралка+сушилка')
    v.f('r', 11.98, 0.19, 12.28, 0.95, 'install', 'инсталляция', h=1.2)
    v.f('r', 11.98, 0.25, 12.58, 0.85, 'wc', 'унитаз', h=0.4, back='w')
    v.f('r', 13.02, -1.80, 13.62, -0.60, 'laundry', 'стирка + сушка в шкафу', h=2.2, back='e')
    v.f('r', 13.02, -0.58, 13.62, 0.05, 'cabinet', 'постельное бельё', h=2.2, back='e')
    v.f('r', 13.12, 0.85, 13.62, 1.43, 'vanity', 'раковина', h=0.85, back='e')
    v.f('r', 11.78, 1.45, 13.62, 2.47, 'shower', 'душ, прозрачное стекло', h=2.1,
        extra=dict(glass='clear', side='n'))
    v.f('r', 11.78, 1.30, 12.05, 1.45, 'shelf', 'ниша-полки', h=1.5, z=0.5)

    # ---------------- Пом. 12: детская гардеробная + кладовая -------------
    # Перегородка у стояка делит 12 на две части: из коридора крыла — детская
    # гардеробная с глажкой и сушкой (рядом со стиралкой в ванной 2), из холла —
    # кладовая для продуктов и хозяйственного (3 м от кухни).
    v.wall('r', 9.47, -1.84, 10.32, -1.84, t=0.08, kind='new')   # закрыть старый проём
    v.wall('r', 9.77, -1.84, 9.77, -0.62, t=0.10, kind='new')
    v.door('r', 10.45, -1.84, 11.15, -1.84, hinge=0, side=-1)
    v.door('n', 6.80, 4.905, 7.55, 4.905, kind='slide')
    v.room('Гардеробная 2', 'r', 10.75, -1.35, 'wood', 'детские вещи, глажка, сушка')
    v.f('r', 11.10, -1.81, 11.66, -0.31, 'closet', 'детская одежда, сезонное', h=3.0, back='e')
    v.f('r', 10.35, -0.45, 10.95, -0.31, 'ironing', 'гладильная доска (откидная)', h=1.4, back='s')
    v.f('r', 9.85, -1.75, 10.45, -1.60, 'dryer_rack', 'сушилка (потолочная)', h=0.1, z=2.4)
    v.room('Кладовая', 'n', 7.05, 5.75, 'wood', 'продукты, хозяйственное')
    v.f('n', 6.62, 5.00, 6.97, 6.34, 'closet', 'полки: продукты', h=3.0, back='w')
    v.f('n', 6.97, 5.99, 7.78, 6.34, 'closet', 'полки: хозяйственное', h=3.0, back='s')
    v.f('n', 7.25, 5.00, 7.75, 5.40, 'robot', 'база робота-пылесоса', h=0.12, back='e')


def kitchen_living(v, layout='A'):
    """Кухня-гостиная (пом. 6 + часть коридора)."""
    v.room('Кухня-гостиная', 'n', 8.6, 1.6, 'wood', 'до 15 человек')
    # новая перегородка с нишей под ТВ, отделяет холл от гостиной
    v.wall('n', 6.60, 3.80, 7.85, 3.80, t=0.30, kind='gkl')
    # кухня вдоль стены 6/7 (r): u 9.56…10.16, v -6.72…-3.45
    K = 'r'
    v.f(K, 9.56, -6.72, 10.16, -6.12, 'fridge', 'холодильник встр. (полный)', h=2.3, back='e')
    v.f(K, 9.56, -6.12, 10.16, -5.52, 'oven_col', 'духовка + СВЧ', h=2.3, back='e')
    v.f(K, 9.56, -5.52, 10.16, -4.62, 'kbase', 'варочная; морозильник под ней', h=0.9, back='e',
        extra=dict(hob=True))
    v.f(K, 9.56, -4.62, 10.16, -4.02, 'kbase', 'посудомойка 60', h=0.9, back='e', extra=dict(dw=True))
    v.f(K, 9.56, -4.02, 10.16, -3.45, 'kbase', 'мойка', h=0.9, back='e', extra=dict(sink=True))
    v.f(K, 9.81, -5.52, 10.16, -3.45, 'kupper', '', h=0.9, z=1.5, back='e')
    v.f(K, 9.70, -5.35, 10.16, -4.80, 'hood', 'вытяжка', h=0.5, z=1.6, back='e')
    if layout == 'A':
        # кофейная станция + винный шкаф: короткий возврат от короба стояка
        v.f(K, 8.89, -3.45, 9.49, -2.90, 'kbase', 'кофе, чайник; винный шкаф внизу', h=0.9, back='s',
            extra=dict(wine=True))
        v.f(K, 8.89, -3.45, 9.49, -3.05, 'glass_cab', 'бокалы (стекл. витрина)', h=0.9, z=1.5, back='s')
        # обеденный стол (раздвижной) вдоль кухни
        v.f(K, 7.35, -6.20, 8.25, -4.15, 'table', 'стол 2,0 м, раздвижной до 2,8', h=0.75,
            extra=dict(chairs=dict(w=3, e=3, n=0, s=1)))
        # угловой диван-кровать у окна W3 и стены 5/6
        v.f('n', 6.62, 0.12, 8.55, 1.12, 'sofa', 'угловой диван-кровать', h=0.85, back='n')
        v.f('n', 6.62, 1.12, 7.62, 3.10, 'sofa_part', '', h=0.85, back='w')
        v.f('n', 6.68, 3.61, 7.80, 3.65, 'tv', 'ТВ 50" в нише', h=0.66, z=0.95, back='s')
        v.f('n', 6.62, 3.30, 7.85, 3.65, 'media', 'тумба', h=0.42, back='s')

def build_variants():
    A = Variant('A', 'Рабочий вариант, ред. 2',
                'Варя в дальней комнате 4, Майя в комнате 5 рядом с кухней. Детская с угловой '
                'кроватью-чердаком, в помещении 12 детская гардеробная и кладовая.')
    common_left(A)
    girl_room_4(A, 'Комната Вари', 'Варя')
    girl_room_5(A, 'Комната Майи', 'Майя')
    wing(A)
    kitchen_living(A, 'A')
    return [A]


# ============================================================================
#  Сборка геометрии
# ============================================================================

def _door_geom(d):
    (x0, y0), (x1, y1) = d['p0'], d['p1']
    a = to_n(d['frame'], x0 * M, y0 * M)
    b = to_n(d['frame'], x1 * M, y1 * M)
    return a, b


def _f_poly(f):
    return mm_rect(f['frame'], f['x0'], f['y0'], f['x1'], f['y1'])


def assemble(v, base):
    mono, gas = base['mono'], base['gas']
    demolished = unary_union(v.demolish) if v.demolish else Polygon()
    gas_kept = gas.difference(demolished)
    removed = gas.intersection(demolished)
    new_parts = {'new': [], 'gkl': []}
    for p, kind in v.new_walls:
        new_parts[kind].append(p)
    new_new = unary_union(new_parts['new']).difference(mono).difference(gas_kept) if new_parts['new'] else Polygon()
    new_gkl = unary_union(new_parts['gkl']).difference(mono).difference(gas_kept).difference(new_new) if new_parts['gkl'] else Polygon()
    walls = {'mono': mono, 'gas': gas_kept, 'new': new_new, 'gkl': new_gkl}
    # проёмы
    doors_out = []
    for d in v.doors:
        a, b = _door_geom(d)
        line = LineString([a, b])
        cut = line.buffer(d['t'] * M / 2, cap_style=2)
        hit_mono = cut.intersection(mono).area
        if hit_mono > 2000:
            print(f'!! {v.id}: дверь {a}->{b} режет монолит ({hit_mono/1e6:.3f} м²)', file=sys.stderr)
        for k in ('gas', 'new', 'gkl'):
            walls[k] = walls[k].difference(cut)
        doors_out.append(dict(kind=d['kind'], a=a, b=b, hinge=d['hinge'], side=d['side'], h=d['h'] * M))
    return walls, removed, doors_out


def rooms_raster(v, walls, doors):
    """Заливка помещений: стены + «закрытые» двери/окна → маски → полигоны."""
    sc = 0.05  # px на мм (20 мм / px)
    ox, oy = -800, -1200
    W, H = int(19500 * sc), int(15000 * sc)
    img = np.zeros((H, W), np.uint8)

    def P(pt):
        return (int(round((pt[0] - ox) * sc)), int(round((pt[1] - oy) * sc)))

    def fill_poly(g, val=255):
        for p in polys(g):
            cv2.fillPoly(img, [np.array([P(q) for q in p.exterior.coords], np.int32)], val)

    for k in ('mono', 'gas', 'new', 'gkl'):
        fill_poly(walls[k])
    for d in doors:
        cv2.line(img, P(d['a']), P(d['b']), 255, 3)
    for w in WINDOWS:
        a = to_n(w['frame'], w['a0'] * M, w['c'] * M)
        b = to_n(w['frame'], w['a1'] * M, w['c'] * M)
        cv2.line(img, P(a), P(b), 255, 6)
    a = to_n('n', ENTRANCE['x0'] * M, ENTRANCE['y'] * M)
    b = to_n('n', ENTRANCE['x1'] * M, ENTRANCE['y'] * M)
    cv2.line(img, P(a), P(b), 255, 6)
    # граница холл / кухня-гостиная (условная, без стены)
    for (a, b) in v_boundaries.get(v.id, []):
        cv2.line(img, P(to_n(a[0], a[1] * M, a[2] * M)), P(to_n(b[0], b[1] * M, b[2] * M)), 255, 2)
    out = []
    for r in v.rooms:
        m = img.copy()
        mask = np.zeros((H + 2, W + 2), np.uint8)
        seed = P(r['seed'])
        if img[seed[1], seed[0]]:
            print(f"!! {v.id}: seed {r['name']} в стене", file=sys.stderr)
            continue
        cv2.floodFill(m, mask, seed, 128)
        region = ((m == 128) * 255).astype(np.uint8)
        # чуть расширяем под стены, чтобы пол заходил под них
        area_px = int((region > 0).sum())
        cs, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cs, key=cv2.contourArea)
        c = cv2.approxPolyDP(c, 1.2, True)
        pts = [((float(q[0][0]) / sc + ox), (float(q[0][1]) / sc + oy)) for q in c]
        if area_px > 60000:
            print(f"!! {v.id}: помещение {r['name']} протекает ({area_px * 400 / 1e6:.1f} м²)", file=sys.stderr)
        out.append(dict(name=r['name'], who=r['who'], floor=r['floor'],
                        area=round(area_px * (1 / sc) ** 2 / 1e6, 2), poly=[[round(x), round(y)] for x, y in pts],
                        label=[round(r['seed'][0]), round(r['seed'][1])]))
    return out


# условные границы зон (без стен) для подсчёта площадей
v_boundaries = {
    'A': [(('n', 7.85, 3.80), ('r', 9.49, -2.99)), (('r', 10.39, -2.99), ('r', 10.39, -1.85))],
}


def furniture_out(v):
    out = []
    for f in v.furniture:
        if f['type'] == 'none':
            continue
        cx, cy = (f['x0'] + f['x1']) / 2, (f['y0'] + f['y1']) / 2
        c = to_n(f['frame'], cx * M, cy * M)
        rot = 43.75 if f['frame'] == 'r' else 0.0
        out.append(dict(type=f['type'], label=f['label'], cx=round(c[0]), cy=round(c[1]),
                        w=round(abs(f['x1'] - f['x0']) * M), d=round(abs(f['y1'] - f['y0']) * M),
                        rot=rot, h=round(f['h'] * M), z=round(f['z'] * M), back=f['back'],
                        extra=f['extra']))
    return out


def geo(g):
    return [dict(outer=[[round(x), round(y)] for x, y in p.exterior.coords],
                 holes=[[[round(x), round(y)] for x, y in h.coords] for h in p.interiors])
            for p in polys(g)]


def windows_out():
    out = []
    for w in WINDOWS:
        a = to_n(w['frame'], w['a0'] * M, w['c'] * M)
        b = to_n(w['frame'], w['a1'] * M, w['c'] * M)
        out.append(dict(id=w['id'], a=[round(a[0]), round(a[1])], b=[round(b[0]), round(b[1])], h=w['h']))
    return out


def main():
    base = load_walls()
    data = dict(ceiling=CEIL, windows=windows_out(),
                risers=[[x, y] for x, y in RISERS],
                entrance=dict(a=to_n('n', ENTRANCE['x0'] * M, ENTRANCE['y'] * M),
                              b=to_n('n', ENTRANCE['x1'] * M, ENTRANCE['y'] * M)),
                panel=geo(mm_rect('n', EL_PANEL['x0'], EL_PANEL['y0'], EL_PANEL['x1'], EL_PANEL['y1'])),
                existing=dict(mono=geo(base['mono']), gas=geo(base['gas'])),
                variants=[])
    for v in build_variants():
        walls, removed, doors = assemble(v, base)
        rooms = rooms_raster(v, walls, doors)
        from shapely.geometry import Polygon as _P
        fur = furniture_out(v)
        ergo = ergonomics.check([g for k in ('mono', 'gas', 'new', 'gkl') for g in polys(walls[k])], fur, rooms, doors)
        bad = [e for e in ergo if e['status'] != 'ok']
        print(f'   эргономика: {len(ergo)} проверок, замечаний {len(bad)}')
        for e in bad:
            print(f"     {e['status']:5} {e['room']:<15} {e['item'][:30]:<30} {e['what']:<28} {e['got']}/{e['need']}")
        data['variants'].append(dict(
            id=v.id, title=v.title, summary=v.summary,
            walls={k: geo(g) for k, g in walls.items()}, removed=geo(removed),
            doors=[dict(d, a=[round(d['a'][0]), round(d['a'][1])], b=[round(d['b'][0]), round(d['b'][1])]) for d in doors],
            rooms=rooms, furniture=fur, ergo=ergo, notes=v.notes))
        tot = sum(r['area'] for r in rooms)
        print(v.id, 'помещений', len(rooms), 'сумма', round(tot, 2))
        for r in rooms:
            print(f"   {r['name']:<16} {r['area']:6.2f}")
    out = os.path.join(HERE, '..', 'data', 'project.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(data, open(out, 'w'), ensure_ascii=False)
    print('->', os.path.normpath(out), os.path.getsize(out) // 1024, 'КБ')


if __name__ == '__main__':
    main()
