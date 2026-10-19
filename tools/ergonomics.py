"""Проверка эргономики: зоны подхода к мебели и распашные двери.

Для каждого предмета строится полоса перед его «рабочей» стороной и ищется,
на сколько миллиметров она свободна от стен и другой мебели. Нормы — в
.claude/skills/interior-ergonomics/SKILL.md.
"""
import math
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

# тип → (сторона: 'front' | 'sides' | 'foot', минимум мм, комфорт мм, что проверяем)
RULES = {
    'wardrobe': [('front', 700, 900, 'подход к распашному шкафу')],
    'closet': [('front', 700, 800, 'подход к системе хранения')],
    'dresser': [('front', 700, 900, 'выдвинуть ящики и присесть')],
    'desk': [('front', 750, 900, 'стул и выход из-за стола')],
    'vanity_table': [('front', 700, 800, 'место для пуфа')],
    'bed': [('foot', 600, 800, 'проход в ногах'), ('side', 600, 700, 'подход сбоку')],
    'kbase': [('front', 1000, 1200, 'рабочая зона кухни')],
    'fridge': [('front', 1000, 1200, 'открыть холодильник')],
    'oven_col': [('front', 1000, 1200, 'открыть духовку')],
    'wc': [('front', 600, 750, 'зона перед унитазом')],
    'vanity': [('front', 700, 800, 'зона перед раковиной')],
    'bath': [('front', 700, 800, 'выйти из ванны')],
    'cabinet': [('front', 650, 800, 'открыть шкаф')],
    'laundry': [('front', 800, 900, 'загрузка стиралки/сушилки')],
    'toys': [('front', 600, 800, 'достать игрушки')],
    'shoe': [('front', 600, 800, 'обуться')],
}
# что не мешает проходу (двигается, висит выше 0,9 м, лежит на полу)
SOFT = {'rug', 'accent', 'tv', 'mirror', 'mirror_round', 'install', 'kupper', 'hood', 'dryer_rack',
        'chair', 'stool', 'robot', 'none'}
SIDE_OK = {'nightstand'}  # тумбы у кровати не считаем помехой подходу сбоку


def footprint(f):
    a = math.radians(f['rot'])
    c, s = math.cos(a), math.sin(a)
    hw, hd = f['w'] / 2, f['d'] / 2
    pts = [(f['cx'] + px * c - py * s, f['cy'] + px * s + py * c)
           for px, py in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd))]
    return Polygon(pts)


def _local(f):
    """Оси предмета: u — вдоль спинки, n — от спинки к лицу (наружу)."""
    a = math.radians(f['rot'])
    ex, ey = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))
    back = f.get('back', 'n')
    if back == 'n':
        nrm, along, depth, width = ey, ex, f['d'], f['w']
    elif back == 's':
        nrm, along, depth, width = (-ey[0], -ey[1]), ex, f['d'], f['w']
    elif back == 'w':
        nrm, along, depth, width = ex, ey, f['w'], f['d']
    else:
        nrm, along, depth, width = (-ex[0], -ex[1]), ey, f['w'], f['d']
    return nrm, along, depth, width


def _strip(cx, cy, nrm, along, off, width, d):
    """Полоса шириной width, глубиной d, начиная на расстоянии off от центра по nrm."""
    hw = width / 2
    p0 = (cx + nrm[0] * off, cy + nrm[1] * off)
    p1 = (cx + nrm[0] * (off + d), cy + nrm[1] * (off + d))
    return Polygon([(p0[0] - along[0] * hw, p0[1] - along[1] * hw), (p0[0] + along[0] * hw, p0[1] + along[1] * hw),
                    (p1[0] + along[0] * hw, p1[1] + along[1] * hw), (p1[0] - along[0] * hw, p1[1] - along[1] * hw)])


def _free_depth(cx, cy, nrm, along, off, width, obstacles, cap=1500):
    width = max(width * 0.4, 50)  # меряем по центральным 40%: углы П-образных систем не в счёт
    lo, hi = 0, cap
    if _strip(cx, cy, nrm, along, off + 5, width, cap).intersection(obstacles).area < 500:
        return cap
    for _ in range(14):
        mid = (lo + hi) / 2
        if _strip(cx, cy, nrm, along, off + 5, width, mid).intersection(obstacles).area < 500:
            lo = mid
        else:
            hi = mid
    return lo


def check(walls, furniture, rooms, doors):
    wall_geom = unary_union([g for g in walls])
    fps = [(f, footprint(f)) for f in furniture]
    out = []

    def room_of(pt):
        for r in rooms:
            if Polygon(r['poly']).buffer(80).contains(Point(pt)):
                return r['name']
        return ''

    for i, (f, fp) in enumerate(fps):
        rules = RULES.get(f['type'])
        if not rules or f.get('z', 0) > 900:
            continue
        if f['type'] == 'wardrobe' and f.get('extra', {}).get('sliding'):
            rules = [('front', 600, 750, 'подход к шкафу-купе')]
        if f['type'] == 'bed' and f.get('extra', {}).get('low'):
            rules = [('side', 600, 700, 'подход к нижней кровати')]
        nrm, along, depth, width = _local(f)
        others = [(o, g) for j, (o, g) in enumerate(fps) if j != i and o['type'] not in SOFT
                  and o.get('z', 0) < 900 and not g.contains(fp.centroid) and not fp.contains(g.centroid)]
        single = 0 < f.get('extra', {}).get('w', 0) < 1.4
        for side, need, comfy, what in rules:
            if side == 'foot' and single:
                continue  # у односпальной кровати у стены проход в ногах не обязателен
            obstacles = unary_union([wall_geom] + [g for (o, g) in others
                                                   if not (side == 'side' and o['type'] in SIDE_OK)])
            res = []
            if side == 'front':
                res.append(('front', _free_depth(f['cx'], f['cy'], nrm, along, depth / 2, width, obstacles), nrm, along, depth / 2, width))
            elif side == 'foot':
                res.append(('foot', _free_depth(f['cx'], f['cy'], nrm, along, depth / 2, width, obstacles), nrm, along, depth / 2, width))
            else:
                # длинные стороны кровати: вдоль ±along, ширина полосы = длина кровати
                for sgn in (1, -1):
                    ax = (along[0] * sgn, along[1] * sgn)
                    res.append(('side', _free_depth(f['cx'], f['cy'], ax, nrm, width / 2, depth, obstacles), ax, nrm, width / 2, depth))
                w_ = f.get('extra', {}).get('w', 0)
                if w_ and w_ < 1.4:  # односпальная: достаточно одной свободной стороны
                    res = [max(res, key=lambda r: r[1])]
            for (sd, got, nv, av, off, wd) in res:
                got = round(got, -1)
                status = 'ok' if got >= comfy else ('tight' if got >= need else 'bad')
                zone = _strip(f['cx'], f['cy'], nv, av, off, wd, min(max(got, 1), need))
                out.append(dict(room=room_of((f['cx'], f['cy'])), item=f['label'] or f['type'], type=f['type'],
                                what=what, need=need, comfy=comfy, got=int(round(min(got, 1500), -1)),
                                status=status,
                                zone=[[round(x), round(y)] for x, y in zone.exterior.coords]))
    # распашные двери: дуга открывания свободна от мебели
    hard = unary_union([g for (o, g) in fps if o['type'] not in SOFT and o.get('z', 0) < 900])
    for d in doors:
        if d['kind'] != 'swing':
            continue
        (ax, ay), (bx, by) = d['a'], d['b']
        L = math.hypot(bx - ax, by - ay)
        nx, ny = -(by - ay) / L * d['side'], (bx - ax) / L * d['side']
        h = (bx, by) if d['hinge'] else (ax, ay)
        arc = Point(h).buffer(L, 32).intersection(
            Polygon([(ax, ay), (bx, by), (bx + nx * L, by + ny * L), (ax + nx * L, ay + ny * L)]))
        hit = arc.intersection(hard).area
        out.append(dict(room=room_of((ax + nx * 300 + (bx - ax) / 2, ay + ny * 300 + (by - ay) / 2)),
                        item='дверь', type='door', what='дверь открывается полностью',
                        need=0, comfy=0, got=int(hit / 1e4), status='ok' if hit < 5e4 else 'bad',
                        zone=[[round(x), round(y)] for x, y in arc.exterior.coords] if arc.geom_type == 'Polygon' else []))
    return out
