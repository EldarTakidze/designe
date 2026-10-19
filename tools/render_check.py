"""Быстрый PNG-рендер плана для проверки (не для заказчика)."""
import json, math, os, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(HERE, '..', 'data', 'project.json')))
vid = sys.argv[1] if len(sys.argv) > 1 else 'A'
out = sys.argv[2] if len(sys.argv) > 2 else '/tmp/plan.png'
box = list(map(float, sys.argv[3:7])) if len(sys.argv) > 6 else [-600, -800, 17600, 14000]
v = next(x for x in data['variants'] if x['id'] == vid)
x0, y0, x1, y1 = box
sc = 2400 / (x1 - x0)
W, H = 2400, int((y1 - y0) * sc)
im = Image.new('RGB', (W, H), 'white')
dr = ImageDraw.Draw(im, 'RGBA')
F = lambda s: ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', s)
T = lambda p: ((p[0] - x0) * sc, (p[1] - y0) * sc)
for gx in range(-1000, 20000, 500):
    dr.line([T((gx, y0)), T((gx, y1))], fill=(235, 238, 250) if gx % 1000 else (205, 212, 240))
for gy in range(-1000, 16000, 500):
    dr.line([T((x0, gy)), T((x1, gy))], fill=(235, 238, 250) if gy % 1000 else (205, 212, 240))
COL = dict(wood=(236, 222, 196, 255), tile=(206, 226, 232, 255), stone=(228, 226, 220, 255))
for r in v['rooms']:
    dr.polygon([T(p) for p in r['poly']], fill=COL[r['floor']])
for k, c in (('mono', (60, 60, 64)), ('gas', (150, 150, 150)), ('new', (200, 80, 60)), ('gkl', (220, 140, 40))):
    for p in v['walls'][k]:
        dr.polygon([T(q) for q in p['outer']], fill=c)
for p in v['removed']:
    dr.polygon([T(q) for q in p['outer']], outline=(220, 0, 0), fill=(255, 0, 0, 40))
for w in data['windows']:
    dr.line([T(w['a']), T(w['b'])], fill=(40, 120, 255), width=5)
for d in v['doors']:
    dr.line([T(d['a']), T(d['b'])], fill=(0, 160, 80), width=3)
for f in v['furniture']:
    a = math.radians(f['rot'])
    c, s = math.cos(a), math.sin(a)
    hw, hd = f['w'] / 2, f['d'] / 2
    pts = [(f['cx'] + px * c - py * s, f['cy'] + px * s + py * c) for px, py in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd))]
    dr.polygon([T(p) for p in pts], outline=(30, 30, 30), fill=(255, 255, 255, 150))
    if f['label']:
        dr.text(T((f['cx'], f['cy'])), f['label'][:22], fill=(120, 20, 20), font=F(11), anchor='mm')
for r in v['rooms']:
    dr.text(T(r['label']), f"{r['name']} {r['area']}", fill=(0, 0, 0), font=F(17), anchor='mm')
for x, y in data['risers']:
    dr.ellipse([T((x - 100, y - 100)), T((x + 100, y + 100))], outline=(255, 0, 0), width=3)
im.save(out)
print(out, im.size)
