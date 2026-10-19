"""Процедурные текстуры для рендеров: ламинат, плитка, грузинский алфавит, ковры."""
import math, os, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT_SERIF = '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'
FONT_SERIF_B = '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'
ASOMTAVRULI = [chr(c) for c in range(0x10A0, 0x10C6)]   # древний грузинский алфавит
MKHEDRULI = [chr(c) for c in range(0x10D0, 0x10F1)]


def _hex(c):
    c = c.lstrip('#')
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def laminate(path, base, var=0.08, plank_w=0.19, plank_l=1.38, size_m=2.76, px=2048, seed=3):
    """Дубовый ламинат: доски со смещением, волокна, лёгкая фаска. Покрывает size_m × size_m."""
    random.seed(seed)
    k = px / size_m
    im = Image.new('RGB', (px, px), _hex(base))
    dr = ImageDraw.Draw(im)
    base = _hex(base)
    rows = int(round(size_m / plank_w))
    for r in range(rows):
        y0 = int(r * plank_w * k)
        y1 = int((r + 1) * plank_w * k)
        off = (r * 0.37 % 1.0) * plank_l
        x = -off
        while x < size_m:
            t = random.uniform(-var, var)
            col = _mix(base, (255, 255, 255) if t > 0 else (60, 40, 20), abs(t))
            x0p, x1p = int(x * k), int((x + plank_l) * k)
            dr.rectangle([x0p, y0, x1p, y1], fill=col)
            # волокна
            for _ in range(int((y1 - y0) * 0.9)):
                yy = random.randint(y0, y1)
                gx0 = random.randint(x0p, max(x0p + 1, x1p))
                ln = random.randint(40, 260)
                g = random.uniform(-0.10, 0.06)
                gc = _mix(col, (40, 25, 10) if g < 0 else (255, 250, 240), abs(g))
                dr.line([gx0, yy, gx0 + ln, yy + random.randint(-2, 2)], fill=gc, width=1)
            # сучки изредка
            if random.random() < 0.18:
                cx, cy = random.randint(x0p, max(x0p + 1, x1p)), random.randint(y0 + 5, max(y0 + 6, y1 - 5))
                rr = random.randint(4, 9)
                dr.ellipse([cx - rr * 2, cy - rr, cx + rr * 2, cy + rr], fill=_mix(col, (60, 35, 15), 0.35))
            dr.line([x0p, y0, x0p, y1], fill=_mix(col, (30, 20, 10), 0.45), width=2)
            x += plank_l
        dr.line([0, y0, px, y0], fill=_mix(base, (30, 20, 10), 0.45), width=2)
    im = im.filter(ImageFilter.GaussianBlur(0.6))
    im.save(path)
    return size_m


def tile(path, base, grout, tile_w=0.6, tile_h=0.6, size_m=2.4, px=1536, veins=None, seed=5, var=0.03):
    random.seed(seed)
    k = px / size_m
    im = Image.new('RGB', (px, px), _hex(grout))
    dr = ImageDraw.Draw(im)
    nx, ny = int(round(size_m / tile_w)), int(round(size_m / tile_h))
    for i in range(nx):
        for j in range(ny):
            t = random.uniform(-var, var)
            col = _mix(_hex(base), (255, 255, 255) if t > 0 else (0, 0, 0), abs(t))
            dr.rectangle([int(i * tile_w * k) + 2, int(j * tile_h * k) + 2,
                          int((i + 1) * tile_w * k) - 2, int((j + 1) * tile_h * k) - 2], fill=col)
    if veins:
        for _ in range(40):
            x, y = random.randint(0, px), random.randint(0, px)
            pts = [(x, y)]
            for _ in range(30):
                x += random.randint(-30, 50)
                y += random.randint(-20, 40)
                pts.append((x, y))
            dr.line(pts, fill=_hex(veins), width=random.randint(1, 3))
        im = im.filter(ImageFilter.GaussianBlur(0.8))
    im.save(path)
    return size_m


def zellige(path, colors, size_m=1.2, tile_m=0.1, px=1536, seed=7):
    """Глазурованная плитка ручной работы (неровный тон)."""
    random.seed(seed)
    k = px / size_m
    im = Image.new('RGB', (px, px), (235, 230, 222))
    dr = ImageDraw.Draw(im)
    n = int(round(size_m / tile_m))
    for i in range(n):
        for j in range(n):
            c = _hex(random.choice(colors))
            t = random.uniform(-0.12, 0.12)
            c = _mix(c, (255, 255, 255) if t > 0 else (0, 0, 0), abs(t))
            x0, y0 = int(i * tile_m * k) + 2, int(j * tile_m * k) + 2
            x1, y1 = int((i + 1) * tile_m * k) - 2, int((j + 1) * tile_m * k) - 2
            dr.rectangle([x0, y0, x1, y1], fill=c)
            for _ in range(6):
                rx, ry = random.randint(x0, x1), random.randint(y0, y1)
                dr.ellipse([rx - 6, ry - 6, rx + 6, ry + 6], fill=_mix(c, (255, 255, 255), 0.08))
    im.filter(ImageFilter.GaussianBlur(1.2)).save(path)


def alphabet_poster(path, paper, ink, accent, w=1400, h=1900, title=True, letters='asomtavruli'):
    """Плакат: 38 букв асомтаврули (древнее письмо) с подписями мхедрули."""
    im = Image.new('RGB', (w, h), _hex(paper))
    dr = ImageDraw.Draw(im)
    big = ImageFont.truetype(FONT_SERIF, 150)
    small = ImageFont.truetype(FONT_SERIF, 34)
    head = ImageFont.truetype(FONT_SERIF_B, 64)
    cols, rows = 6, 7
    mx, my = 120, 260 if title else 140
    cw, ch = (w - 2 * mx) / cols, (h - my - 120) / rows
    if title:
        dr.text((w / 2, 130), 'ანბანი', font=head, fill=_hex(accent), anchor='mm')
        dr.line([w / 2 - 160, 190, w / 2 + 160, 190], fill=_hex(accent), width=3)
    seq = ASOMTAVRULI if letters == 'asomtavruli' else MKHEDRULI
    kids = ['#2F4A3F', '#A65A3C', '#C9A04A', '#5A1F2A', '#4E7A8C']
    for i, ch_ in enumerate(seq[:cols * rows]):
        cx = mx + (i % cols + 0.5) * cw
        cy = my + (i // cols + 0.45) * ch
        dr.text((cx, cy), ch_, font=big, fill=_hex(ink) if letters == 'asomtavruli' else _hex(kids[i % len(kids)]),
                anchor='mm')
        if i < len(MKHEDRULI) and letters == 'asomtavruli':
            dr.text((cx, cy + 105), MKHEDRULI[i], font=small, fill=_hex(accent), anchor='mm')
    im.save(path)


def alphabet_mural(path, bg, ink, w=3000, h=1600, seed=2):
    """Крупная надпись-фриз: тон-в-тон буквы асомтаврули для стены."""
    random.seed(seed)
    im = Image.new('RGB', (w, h), _hex(bg))
    dr = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT_SERIF, 260)
    x, y = 60, 40
    letters = ASOMTAVRULI * 2
    i = 0
    while y < h - 100:
        ch_ = letters[i % len(letters)]
        dr.text((x, y), ch_, font=f, fill=_hex(ink))
        x += 230
        if x > w - 200:
            x = 60 + (110 if (y // 300) % 2 == 0 else 0)
            y += 300
        i += 1
    im.save(path)


def rug(path, base, line, accent, w=1600, h=1200, kind='plain', seed=11):
    random.seed(seed)
    im = Image.new('RGB', (w, h), _hex(base))
    dr = ImageDraw.Draw(im)
    if kind == 'border':
        for m, c in ((50, line), (90, accent)):
            dr.rectangle([m, m, w - m, h - m], outline=_hex(c), width=10)
    elif kind == 'kilim':
        # мотив, навеянный грузинскими коврами: ромбы и крест-звёзды
        for j in range(4):
            for i in range(6):
                cx, cy = (i + 0.5) * w / 6, (j + 0.5) * h / 4
                s = 70
                dr.polygon([(cx, cy - s), (cx + s, cy), (cx, cy + s), (cx - s, cy)], outline=_hex(line), width=8)
                dr.rectangle([cx - 14, cy - 14, cx + 14, cy + 14], fill=_hex(accent))
        dr.rectangle([30, 30, w - 30, h - 30], outline=_hex(accent), width=24)
    # ворс
    px = im.load()
    for _ in range(w * h // 6):
        x, y = random.randrange(w), random.randrange(h)
        r, g, b = px[x, y]
        d = random.randint(-12, 12)
        px[x, y] = (max(0, min(255, r + d)), max(0, min(255, g + d)), max(0, min(255, b + d)))
    im.filter(ImageFilter.GaussianBlur(1.0)).save(path)


def linen(path, base, px=512, seed=4):
    random.seed(seed)
    im = Image.new('RGB', (px, px), _hex(base))
    dr = ImageDraw.Draw(im)
    for i in range(0, px, 3):
        t = random.uniform(-0.05, 0.05)
        c = _mix(_hex(base), (255, 255, 255) if t > 0 else (0, 0, 0), abs(t))
        dr.line([0, i, px, i], fill=c)
        t = random.uniform(-0.04, 0.04)
        c = _mix(_hex(base), (255, 255, 255) if t > 0 else (0, 0, 0), abs(t))
        dr.line([i, 0, i, px], fill=c)
    im.filter(ImageFilter.GaussianBlur(0.5)).save(path)


def art(path, palette, w=1000, h=1300, seed=1, kind='arches'):
    """Простая абстрактная графика для рамок (арки, холмы — как силуэты Кавказа)."""
    random.seed(seed)
    im = Image.new('RGB', (w, h), _hex(palette[0]))
    dr = ImageDraw.Draw(im)
    if kind == 'mountains':
        for k, c in enumerate(palette[1:]):
            base = h * (0.45 + 0.15 * k)
            pts = [(0, h)]
            x = 0
            while x <= w:
                pts.append((x, base - random.randint(0, int(h * 0.18))))
                x += random.randint(80, 200)
            pts += [(w, h)]
            dr.polygon(pts, fill=_hex(c))
        dr.ellipse([w * 0.65, h * 0.15, w * 0.8, h * 0.15 + w * 0.15], fill=_hex(palette[-1]))
    else:
        for k, c in enumerate(palette[1:]):
            x0 = w * 0.15 + k * w * 0.18
            dr.rectangle([x0, h * 0.45, x0 + w * 0.28, h * 0.9], fill=_hex(c))
            dr.ellipse([x0, h * 0.31, x0 + w * 0.28, h * 0.59], fill=_hex(c))
    im.save(path)
