"""Сцена Blender из data/project.json и рендер Cycles.

Запуск:  python3 tools/render/scene.py --variant B --style warm --view kl_entry \
             --out renders/warm_kl_entry.png --samples 160 --res 1600x1000
Координаты плана: мм, Y вниз. В Blender: X = x/1000, Y = -y/1000, Z вверх.
"""
import argparse, json, math, os, random, sys
import bpy, bmesh
from mathutils import Vector
import shapely
from shapely.geometry import Polygon, MultiPolygon, LineString, Point
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
from styles import STYLES  # noqa: E402
import textures as TX  # noqa: E402

CEIL = 3.262
TEX = os.path.join(ROOT, 'renders', 'tex')
os.makedirs(TEX, exist_ok=True)


# ---------------------------------------------------------------- утилиты ---
def lin(c):
    c = c.lstrip('#')
    out = []
    for i in (0, 2, 4):
        v = int(c[i:i + 2], 16) / 255
        out.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return (*out, 1.0)


def P(x, y):
    """Точка плана (мм) → Blender (м)."""
    return (x / 1000.0, -y / 1000.0)


MATS = {}


def mat(name, color='#ffffff', rough=0.5, metal=0.0, tex=None, size=1.0, bump=0.0, coords='Object',
        emit=None, emit_str=0.0, sheen=0.0, coat=0.0, trans=0.0, sss=0.0, proj='BOX', alpha=1.0):
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = lin(color)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    if sheen:
        b.inputs['Sheen Weight'].default_value = sheen
    if coat:
        b.inputs['Coat Weight'].default_value = coat
    if trans:
        b.inputs['Transmission Weight'].default_value = trans
    if sss:
        b.inputs['Subsurface Weight'].default_value = sss
    if emit:
        b.inputs['Emission Color'].default_value = lin(emit)
        b.inputs['Emission Strength'].default_value = emit_str
    if alpha < 1:
        b.inputs['Alpha'].default_value = alpha
    if tex:
        tc = nt.nodes.new('ShaderNodeTexCoord')
        mp = nt.nodes.new('ShaderNodeMapping')
        im = nt.nodes.new('ShaderNodeTexImage')
        im.image = bpy.data.images.load(tex, check_existing=True)
        if coords in ('Object', 'Generated') and proj == 'BOX':
            im.projection = 'BOX'
            im.projection_blend = 0.15
        nt.links.new(tc.outputs[coords], mp.inputs['Vector'])
        if coords == 'Object':
            mp.inputs['Scale'].default_value = (1 / size, 1 / size, 1 / size)
        nt.links.new(mp.outputs['Vector'], im.inputs['Vector'])
        nt.links.new(im.outputs['Color'], b.inputs['Base Color'])
        if bump:
            bp = nt.nodes.new('ShaderNodeBump')
            bp.inputs['Strength'].default_value = bump
            nt.links.new(im.outputs['Color'], bp.inputs['Height'])
            nt.links.new(bp.outputs['Normal'], b.inputs['Normal'])
    MATS[name] = m
    return m


def glass_mat():
    if 'glass' in MATS:
        return MATS['glass']
    m = bpy.data.materials.new('glass')
    m.use_nodes = True
    nt = m.node_tree
    out = nt.nodes['Material Output']
    for n in list(nt.nodes):
        if n != out:
            nt.nodes.remove(n)
    tr = nt.nodes.new('ShaderNodeBsdfTransparent')
    gl = nt.nodes.new('ShaderNodeBsdfGlossy')
    gl.inputs['Roughness'].default_value = 0.02
    mix = nt.nodes.new('ShaderNodeMixShader')
    mix.inputs['Fac'].default_value = 0.08
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(gl.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    MATS['glass'] = m
    return m


def sheer_mat(color):
    key = 'sheer' + color
    if key in MATS:
        return MATS[key]
    m = bpy.data.materials.new(key)
    m.use_nodes = True
    nt = m.node_tree
    out = nt.nodes['Material Output']
    for n in list(nt.nodes):
        if n != out:
            nt.nodes.remove(n)
    tl = nt.nodes.new('ShaderNodeBsdfTranslucent')
    tl.inputs['Color'].default_value = lin(color)
    df = nt.nodes.new('ShaderNodeBsdfDiffuse')
    df.inputs['Color'].default_value = lin(color)
    tr = nt.nodes.new('ShaderNodeBsdfTransparent')
    m1 = nt.nodes.new('ShaderNodeMixShader')
    m1.inputs['Fac'].default_value = 0.45
    nt.links.new(df.outputs[0], m1.inputs[1])
    nt.links.new(tl.outputs[0], m1.inputs[2])
    m2 = nt.nodes.new('ShaderNodeMixShader')
    m2.inputs['Fac'].default_value = 0.25
    nt.links.new(m1.outputs[0], m2.inputs[1])
    nt.links.new(tr.outputs[0], m2.inputs[2])
    nt.links.new(m2.outputs[0], out.inputs['Surface'])
    MATS[key] = m
    return m


def emissive(name, color, strength):
    return mat(name, color, rough=1, emit=color, emit_str=strength)


COLL = None


def link(obj):
    COLL.objects.link(obj)
    return obj


def mesh_obj(name, verts, faces, m, parent=None, smooth=False, uvs=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    if uvs:
        uv = me.uv_layers.new()
        for poly in me.polygons:
            for li in poly.loop_indices:
                vi = me.loops[li].vertex_index
                uv.data[li].uv = uvs[vi]
    me.update()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    o = bpy.data.objects.new(name, me)
    o.data.materials.append(m)
    if parent:
        o.parent = parent
    return link(o)


def box(w, d, h, x, y, z, m, parent=None, bevel=0.003, seg=2, name='box'):
    """Прямоугольник w (X) × d (Y) × h (Z), центр по XY, низ на z."""
    hw, hd = w / 2, d / 2
    v = [(x - hw, y - hd, z), (x + hw, y - hd, z), (x + hw, y + hd, z), (x - hw, y + hd, z),
         (x - hw, y - hd, z + h), (x + hw, y - hd, z + h), (x + hw, y + hd, z + h), (x - hw, y + hd, z + h)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    o = mesh_obj(name, v, f, m, parent)
    if bevel and min(w, d, h) > bevel * 2.5:
        md = o.modifiers.new('bev', 'BEVEL')
        md.width = bevel
        md.segments = seg
        md.limit_method = 'ANGLE'
        md.harden_normals = False
        for p in o.data.polygons:
            p.use_smooth = seg > 2
    return o


def cyl(r, h, x, y, z, m, parent=None, seg=32, r2=None, name='cyl'):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r, radius2=r if r2 is None else r2,
                          depth=h)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me)
    o.data.materials.append(m)
    o.location = (x, y, z + h / 2)
    if parent:
        o.parent = parent
    return link(o)


def sphere(r, x, y, z, m, parent=None, scale=(1, 1, 1), sub=2, name='sph'):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=r)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me)
    o.data.materials.append(m)
    o.location = (x, y, z)
    o.scale = scale
    if parent:
        o.parent = parent
    return link(o)


def lathe(profile, x, y, z, m, parent=None, steps=40, name='lathe'):
    """profile: [(r, h)] снизу вверх; тело вращения вокруг Z."""
    bm = bmesh.new()
    vs = [bm.verts.new((r, 0, h)) for r, h in profile]
    es = [bm.edges.new((vs[i], vs[i + 1])) for i in range(len(vs) - 1)]
    bmesh.ops.spin(bm, geom=vs + es, cent=(0, 0, 0), axis=(0, 0, 1), angle=math.tau, steps=steps,
                   use_merge=True)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me)
    o.data.materials.append(m)
    o.location = (x, y, z)
    if parent:
        o.parent = parent
    return link(o)


def quad(p0, p1, p2, p3, m, parent=None, name='quad'):
    """Четырёхугольник с UV 0..1 (p0 — низ-лево, по часовой против)."""
    return mesh_obj(name, [p0, p1, p2, p3], [(0, 1, 2, 3)], m, parent, uvs=[(0, 0), (1, 0), (1, 1), (0, 1)])


def empty(name, x, y, rot, parent=None):
    e = bpy.data.objects.new(name, None)
    e.location = (x, y, 0)
    e.rotation_euler = (0, 0, rot)
    if parent:
        e.parent = parent
    return link(e)


def extrude(poly, z0, z1, m, name='ext'):
    """Полигон shapely (в мм плана) с дырами → призма."""
    tris = shapely.constrained_delaunay_triangles(poly)
    verts, idx, faces = [], {}, []

    def vid(x, y, z):
        k = (round(x, 1), round(y, 1), round(z, 4))
        if k not in idx:
            idx[k] = len(verts)
            bx, by = P(x, y)
            verts.append((bx, by, z))
        return idx[k]

    for t in tris.geoms:
        c = list(t.exterior.coords)[:3]
        top = [vid(x, y, z1) for x, y in c]
        bot = [vid(x, y, z0) for x, y in c]
        faces.append(tuple(top))
        faces.append(tuple(reversed(bot)))
    for ring in [poly.exterior] + list(poly.interiors):
        c = list(ring.coords)
        for i in range(len(c) - 1):
            (x0, y0), (x1, y1) = c[i], c[i + 1]
            faces.append((vid(x0, y0, z0), vid(x1, y1, z0), vid(x1, y1, z1), vid(x0, y0, z1)))
    o = mesh_obj(name, verts, faces, m)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(o.data)
    bm.free()
    return o


def polys(geo):
    out = []
    for p in geo:
        out.append(Polygon(p['outer'], [h for h in p['holes']]))
    return out


# ----------------------------------------------------------------- стиль ---
class Kit:
    """Материалы стиля."""

    def __init__(self, S, key):
        self.S = S
        lam = os.path.join(TEX, f'lam_{key}.png')
        if not os.path.exists(lam):
            TX.laminate(lam, S['laminate'], var=S['lam_var'])
        veneer = os.path.join(TEX, f'ven_{key}.png')
        if not os.path.exists(veneer):
            TX.laminate(veneer, S['wood'], var=0.04, plank_w=0.6, plank_l=2.4, size_m=1.2, seed=9)
        bf = S['bath_floor']
        bt = os.path.join(TEX, f'bath_{key}.png')
        if not os.path.exists(bt):
            TX.tile(bt, bf[0], bf[1], veins=bf[2])
        self.floor = mat('floor_' + key, tex=lam, size=2.76, rough=0.45, bump=0.08, coords='Object')
        self.bath_floor = mat('bathf_' + key, tex=bt, size=2.4, rough=0.25, coords='Object')
        self.wall = mat('wall_' + key, S['wall'], rough=0.9)
        self.ceiling = mat('ceil_' + key, S['ceiling'], rough=0.95)
        self.wood = mat('wood_' + key, tex=veneer, size=1.2, rough=0.5, bump=0.03)
        self.walnut = mat('walnut', tex=self._ven('#6E4A2E', 'walnut'), size=1.2, rough=0.45, bump=0.03)
        self.oak = mat('oakven', tex=self._ven('#C9A273', 'oak'), size=1.2, rough=0.5, bump=0.03)
        self.front = mat('front_' + key, S['k_front'], rough=0.55)
        self.worktop = mat('worktop_' + key, S['worktop'], rough=0.3)
        self.metal = mat('metal_' + key, S['metal'], rough=0.3, metal=1.0)
        self.black = mat('black', '#1E1E1E', rough=0.4)
        self.steel = mat('steel', '#C8CBCC', rough=0.25, metal=1.0)
        self.white = mat('white', '#F3F1EC', rough=0.5)
        self.ceramic = mat('ceramic', '#FAFAF8', rough=0.12, coat=0.3)
        self.screen = mat('screen', '#0B0C0D', rough=0.15)
        self.mirror = mat('mirror', '#E8EEF0', rough=0.02, metal=1.0)
        self.frame = mat('winframe', '#2C2D2E', rough=0.45, metal=0.3)
        self.glass = glass_mat()
        self.sofa = mat('sofa_' + key, S['sofa'], rough=0.95, sheen=0.6)
        self.cush = [mat(f'cush{i}_' + key, c, rough=0.95, sheen=0.5) for i, c in enumerate(S['cushions'])]
        self.throw = mat('throw_' + key, S['throw'], rough=1.0, sheen=0.4)
        self.chair_fabric = mat('chf_' + key, S['chair_fabric'], rough=0.95, sheen=0.4)
        self.bed_fabric = mat('bedf_' + key, S['bed_fabric'], rough=0.95, sheen=0.4)
        self.bedding = [mat(f'bedding{i}_' + key, c, rough=1.0, sheen=0.3) for i, c in enumerate(S['bedding'])]
        self.terracotta = mat('qvevri_' + key, S['qvevri'], rough=0.8)
        self.leaf = mat('leaf', '#6E7F5A', rough=0.6, sss=0.15)
        self.trunk = mat('trunk', '#5A4A3A', rough=0.9)
        self.pot = mat('pot', '#D8D2C8', rough=0.7)
        self.pomegranate = mat('pomegranate', '#8E1F24', rough=0.35, coat=0.4)
        self.wineglass = mat('wineglass', '#F4F8FA', rough=0.02, trans=1.0)
        self.bottle = mat('bottle', '#1D2A1E', rough=0.1, coat=0.5)
        self.led = emissive('led', '#FFE2B8', 6.0)
        self.paper = mat('paper', '#F1ECE3', rough=1.0)
        self.books = [mat(f'book{i}', c, rough=0.8) for i, c in enumerate(
            ['#8C4A32', '#D9CFC0', '#3B4A42', '#B08D57', '#5A1F2A', '#EAE4DA'])]
        self.accent = mat('accentc_' + key, S['accents'], rough=0.8)
        if S['backsplash'] == 'zellige' or S['bath_wall'] == 'zellige':
            z = os.path.join(TEX, f'zellige_{key}.png')
            if not os.path.exists(z):
                TX.zellige(z, ['#2F4A3F', '#35574A', '#2A4238'])
            self.zellige = mat('zellige_' + key, tex=z, size=1.2, rough=0.15, coat=0.6, bump=0.15)
        self.backsplash = self.zellige if S['backsplash'] == 'zellige' else mat('bs_' + key, S['backsplash'], rough=0.3)
        self.curtain = sheer_mat(S['curtain'])

    def _ven(self, c, n):
        p = os.path.join(TEX, f'ven_{n}.png')
        if not os.path.exists(p):
            TX.laminate(p, c, var=0.04, plank_w=0.6, plank_l=2.4, size_m=1.2, seed=13)
        return p

    def table_wood(self):
        return self.walnut if self.S['table'] == 'walnut' else self.oak


# ---------------------------------------------------------------- мебель ---
def build_item(f, K, root):
    back = f.get('back', 'n')
    swap = back in ('w', 'e')
    W = (f['d'] if swap else f['w']) / 1000
    D = (f['w'] if swap else f['d']) / 1000
    H = f['h'] / 1000
    Z = f.get('z', 0) / 1000
    x, y = P(f['cx'], f['cy'])
    g = empty('grp_' + f['type'], x, y, -math.radians(f['rot']), root)
    inner = empty('in', 0, 0, {'n': 0, 's': math.pi, 'w': math.pi / 2, 'e': -math.pi / 2}[back], g)
    t, ex = f['type'], f.get('extra', {})
    by, fy = D / 2, -D / 2   # +Y — спинка (к стене), −Y — лицо
    S = K.S

    def B(w, d, h, xx, yy, zz, m, bevel=0.003, seg=2):
        return box(w, d, h, xx, yy, zz, m, inner, bevel, seg)

    def fronts(w, h, z0, n, m, y0=None, gap=0.003):
        y0 = fy if y0 is None else y0
        for i in range(n):
            B(w / n - gap, 0.018, h - gap, -w / 2 + (i + .5) * w / n, y0 - 0.009, z0, m, 0.002)

    if t == 'sofa' or t == 'sofa_part':
        B(W, D, 0.12, 0, 0, 0.0, K.black, 0.01)
        B(W, D - 0.02, 0.26, 0, 0, 0.1, K.sofa, 0.03, 4)
        n = max(1, round(W / 0.75))
        for i in range(n):
            B(W / n - 0.02, D - 0.3, 0.14, -W / 2 + (i + .5) * W / n, -0.13, 0.36, K.sofa, 0.05, 5)
        B(W, 0.22, 0.4, 0, by - 0.11, 0.36, K.sofa, 0.06, 5)
        for i in range(n):
            if random.random() < 0.8:
                B(0.42, 0.13, 0.38, -W / 2 + (i + .5) * W / n + random.uniform(-.1, .1), by - 0.3, 0.48,
                  random.choice(K.cush), 0.06, 6).rotation_euler = (math.radians(-12), 0, random.uniform(-.15, .15))
        if t == 'sofa':
            B(0.5, D - 0.25, 0.04, W / 2 - 0.35, -0.1, 0.5, K.throw, 0.02, 3)
    elif t == 'table':
        tw = K.table_wood()
        LW, LD = f['w'] / 1000, f['d'] / 1000
        box(LW, LD, 0.035, 0, 0, 0.715, tw, inner, 0.008, 3)
        for sy in (-1, 1):
            box(0.07, 0.07, 0.715, 0, sy * LD * 0.3, 0, K.black if S['chair'] != 'oak_linen' else tw, inner, 0.01)
        box(0.06, LD * 0.62, 0.05, 0, 0, 0.08, K.black if S['chair'] != 'oak_linen' else tw, inner, 0.01)
        c = ex.get('chairs', {})
        cw = 0.46

        def chair(xx, yy, rot):
            cg = empty('chair', xx, yy, rot, inner)
            frame = K.table_wood() if S['chair'] == 'oak_linen' else K.black
            if S['chair'] == 'bentwood':
                for sx, sy2 in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                    cyl(0.014, 0.45, sx * 0.18, sy2 * 0.18, 0, frame, cg, 12)
                cyl(0.21, 0.03, 0, 0, 0.45, K.chair_fabric, cg, 32)
                bk = cyl(0.012, 0.42, 0, 0.2, 0.47, frame, cg, 12)
                box(0.38, 0.02, 0.07, 0, 0.2, 0.8, frame, cg, 0.008, 3)
                return
            for sx, sy2 in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                box(0.03, 0.03, 0.45, sx * 0.19, sy2 * 0.19, 0, frame, cg, 0.004)
            box(0.44, 0.44, 0.05, 0, 0, 0.43, K.chair_fabric if S['chair'] == 'oak_linen' else K.chair_fabric, cg, 0.015, 3)
            box(0.42, 0.03, 0.34, 0, 0.21, 0.5, frame if S['chair'] == 'black_wood' else K.chair_fabric, cg, 0.012, 3)

        def nn(k, i):
            return (i + 1) / (k + 1)
        for i in range(c.get('w', 0)):
            chair(-LW / 2 - cw / 2 + .08, LD / 2 - nn(c['w'], i) * LD, math.pi / 2)
        for i in range(c.get('e', 0)):
            chair(LW / 2 + cw / 2 - .08, LD / 2 - nn(c['e'], i) * LD, -math.pi / 2)
        for i in range(c.get('n', 0)):
            chair(-LW / 2 + nn(c['n'], i) * LW, LD / 2 + cw / 2 - .08, 0)
        for i in range(c.get('s', 0)):
            chair(-LW / 2 + nn(c['s'], i) * LW, -LD / 2 - cw / 2 + .08, math.pi)
        # гранаты в чаше
        lathe([(0.0, 0), (0.08, 0.0), (0.14, 0.05), (0.16, 0.09), (0.15, 0.09), (0.13, 0.05), (0.07, 0.01), (0, 0.01)],
              0, 0, 0.75, K.ceramic, inner)
        for i in range(5):
            a = i / 5 * math.tau
            sphere(0.045, math.cos(a) * 0.06, math.sin(a) * 0.06, 0.82, K.pomegranate, inner)
        sphere(0.045, 0, 0, 0.87, K.pomegranate, inner)
    elif t == 'coffee':
        cyl(min(W, D) / 2, 0.03, 0, 0, 0.4, K.table_wood(), inner, 48)
        cyl(0.05, 0.4, 0, 0, 0, K.black, inner, 24)
        for i in range(3):
            box(0.2, 0.26, 0.025, 0.02 * i, 0, 0.43 + i * 0.025, K.books[i], inner, 0.002)
    elif t in ('kbase',):
        B(W, D - 0.05, 0.1, 0, 0.04, 0, K.black, 0)
        B(W, D - 0.02, 0.8, 0, 0.01, 0.1, K.front, 0.002)
        fronts(W, 0.78, 0.11, max(1, round(W / 0.6)), K.front)
        B(W + 0.004, D + 0.01, 0.03, 0, -0.005, 0.9, K.worktop, 0.002)
        B(W, 0.012, 0.6, 0, by - 0.006, 0.93, K.backsplash, 0)
        if ex.get('hob'):
            B(0.58, 0.5, 0.006, 0, -0.02, 0.93, K.screen, 0.001)
        if ex.get('sink'):
            B(0.5, 0.4, 0.004, 0, -0.03, 0.93, K.steel, 0.001)
            cyl(0.012, 0.32, 0, by - 0.08, 0.93, K.metal if S['metal'] != '#2B2A28' else K.black, inner, 16)
            box(0.02, 0.18, 0.02, 0, by - 0.16, 1.23, K.metal if S['metal'] != '#2B2A28' else K.black, inner, 0.005)
        if ex.get('wine'):
            B(W * 0.8, 0.02, 0.7, 0, fy - 0.006, 0.14, K.screen, 0.002)
            box(0.24, 0.3, 0.32, -W / 4, 0, 0.93, K.black, inner, 0.01)
            cyl(0.07, 0.2, W / 4, 0, 0.93, K.steel, inner, 24)
    elif t == 'kupper':
        B(W, D, H, 0, 0, Z, K.front if S['k_column'] != 'oak_slats' else K.wood, 0.002)
        B(W - 0.02, D - 0.04, 0.012, 0, 0, Z - 0.012, K.led, 0)
    elif t == 'hood':
        pass
    elif t in ('fridge', 'oven_col'):
        hh = min(H, CEIL - 0.02)
        colm = K.wood if S['k_column'] in ('oak', 'oak_slats') else K.front
        B(W, D, hh, 0, 0, 0, colm, 0.002)
        if t == 'oven_col':
            B(W - 0.06, 0.012, 0.58, 0, fy - 0.004, 0.75, K.screen, 0.002)
            B(W - 0.06, 0.012, 0.44, 0, fy - 0.004, 1.4, K.screen, 0.002)
        if S['k_column'] == 'oak_slats':
            for i in range(int(W / 0.04)):
                B(0.02, 0.012, hh - 0.1, -W / 2 + 0.02 + i * 0.04, fy - 0.008, 0.05, K.wood, 0.002)
    elif t == 'buffet':
        B(W, D, 0.85, 0, 0, 0, K.front if S['k_column'] == 'front' else K.wood, 0.002)
        fronts(W, 0.83, 0.02, max(1, round(W / 0.45)), K.front if S['k_column'] == 'front' else K.wood)
        B(W + 0.004, D + 0.01, 0.03, 0, 0, 0.85, K.worktop, 0.002)
        if ex.get('tv'):
            B(1.23, 0.04, 0.72, 0, fy - 0.12, 1.15, K.screen, 0.004)
            for i in range(4):
                box(0.03, 0.22 + 0.02 * i, 0.24, -W / 3 + i * 0.035, 0, 0.88, K.books[i], inner, 0.002)
            lathe([(0, 0), (0.05, 0), (0.07, 0.08), (0.05, 0.22), (0.02, 0.28), (0.022, 0.3), (0, 0.3)],
                  W / 3, 0, 0.88, K.terracotta, inner)
        else:
            top = CEIL - 0.02
            B(W, D, top - 1.45, 0, 0, 1.45, K.front if S['k_column'] == 'front' else K.wood, 0.002)
            if ex.get('glass'):
                B(W - 0.08, D - 0.08, top - 1.55, 0, -0.01, 1.5, K.wall, 0.0)
                for k in range(3):
                    zz = 1.55 + k * 0.4
                    B(W - 0.1, D - 0.1, 0.012, 0, 0, zz - 0.012, K.white, 0.001)
                    for i in range(3):
                        lathe([(0, 0), (0.035, 0), (0.035, 0.005), (0.004, 0.01), (0.004, 0.1), (0.03, 0.11),
                               (0.04, 0.15), (0.035, 0.2), (0.033, 0.2), (0.038, 0.15), (0.028, 0.115), (0, 0.112)],
                              -W / 3 + i * W / 3, 0, zz, K.wineglass, inner, 24)
                B(W - 0.04, 0.008, top - 1.5, 0, fy - 0.004, 1.47, K.glass, 0)
                B(W - 0.1, 0.01, 0.01, 0, fy + 0.03, top - 0.03, K.led, 0)
            if ex.get('coffee'):
                B(W - 0.08, D - 0.08, 0.55, 0, -0.01, 0.88, K.backsplash, 0.0)
                box(0.24, 0.3, 0.34, 0, -0.03, 0.88, K.black, inner, 0.01)
                cyl(0.07, 0.22, 0, -0.18, 0.88, K.metal, inner, 24)
    elif t in ('wardrobe', 'closet', 'pantry', 'cabinet', 'laundry', 'wine_col', 'glass_cab'):
        hh = min(H, CEIL - 0.02)
        z0 = Z if t == 'glass_cab' else 0
        m = K.wood if t == 'closet' else K.white
        B(W, D, hh, 0, 0, z0, m, 0.002)
        n = ex.get('sections') or max(1, round(W / 0.5))
        if t != 'closet':
            fronts(W, hh - 0.01, z0 + 0.005, n, m)
        if t == 'wine_col':
            B(W - 0.06, 0.01, hh - 0.4, 0, fy - 0.012, 0.15, K.screen, 0.002)
    elif t == 'bed':
        bw = ex.get('w', W)
        B(W, D, 0.3, 0, 0, 0, K.bed_fabric, 0.02, 3)
        B(W - 0.04, D - 0.06, 0.2, 0, -0.02, 0.3, K.bedding[0], 0.05, 4)
        B(W + 0.06, 0.1, 1.05, 0, by - 0.05, 0, K.bed_fabric, 0.03, 4)
        npil = 2 if W > 1.3 else 1
        for i in range(npil):
            B(W / npil - 0.14, 0.38, 0.14, -W / 2 + (i + .5) * W / npil, by - 0.35, 0.48, K.bedding[0], 0.06, 5)
        B(W + 0.02, D * 0.45, 0.05, 0, fy + D * 0.24, 0.49, K.bedding[1], 0.02, 3)
    elif t == 'loft':
        pz = 1.35
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            B(0.06, 0.06, pz + 0.4, sx * (W / 2 - 0.03), sy * (D / 2 - 0.03), 0, K.wood, 0.004)
        B(W, D, 0.06, 0, 0, pz, K.wood, 0.004)
        B(W - 0.06, D - 0.06, 0.15, 0, 0, pz + 0.06, K.bedding[0], 0.04, 4)
        B(W * 0.7, 0.03, 0.3, -W * 0.15, fy + 0.015, pz + 0.06, K.wood, 0.004)
    elif t == 'desk' or t == 'vanity_table':
        B(W, D, 0.03, 0, 0, 0.72, K.wood, 0.004)
        for sx in (-1, 1):
            B(0.03, D - 0.04, 0.72, sx * (W / 2 - 0.03), 0, 0, K.black, 0.004)
    elif t in ('chair', 'stool'):
        B(W * 0.9, D * 0.9, 0.04, 0, 0, 0.44, K.chair_fabric, 0.01, 3)
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            B(0.025, 0.025, 0.44, sx * W * 0.38, sy * D * 0.38, 0, K.black, 0.003)
    elif t in ('nightstand', 'dresser', 'media', 'shoe', 'toys', 'bench'):
        B(W, D, H - (0.05 if Z == 0 else 0), 0, 0, Z if Z else 0.05, K.wood, 0.003)
    elif t == 'rug':
        rk = S['rug']
        rp = os.path.join(TEX, f'rug_{rk[0]}_{rk[1][1:]}.png')
        if not os.path.exists(rp):
            TX.rug(rp, rk[1], rk[2], rk[3], kind=rk[0])
        rm = mat('rug_' + rp, tex=rp, coords='UV', rough=1.0, sheen=0.5)
        o = quad((-W / 2, -D / 2, 0.006), (W / 2, -D / 2, 0.006), (W / 2, D / 2, 0.006), (-W / 2, D / 2, 0.006), rm, inner)
    elif t == 'tv':
        B(W, 0.04, H, 0, 0, Z, K.screen, 0.004)
    elif t == 'accent':
        acc = S['accent_wall'] or S['accents']
        B(W, D, CEIL - 0.03, 0, 0, 0, mat('accentwall_' + acc, acc, rough=0.85), 0)
        # латунные бра над тумбами
        for sy in (-1, 1):
            sphere(0.06, sy * 1.25, fy - 0.08, 0.95, emissive('sconce', '#FFE0B8', 8), inner, sub=3)
            box(0.03, 0.1, 0.03, sy * 1.25, fy - 0.02, 0.92, K.metal, inner, 0.005)
    elif t in ('install', 'none', 'robot'):
        pass
    elif t == 'wc':
        lathe([(0, 0.0), (0.12, 0.0), (0.18, 0.15), (0.19, 0.38), (0.16, 0.4), (0, 0.4)], 0, by - 0.3, 0, K.ceramic, inner)
    elif t == 'vanity':
        B(W, D - 0.02, 0.45, 0, 0, 0.4, K.wood, 0.003)
        B(W, D, 0.03, 0, 0, 0.85, K.worktop, 0.002)
        lathe([(0, 0), (0.15, 0), (0.2, 0.1), (0.19, 0.12), (0, 0.04)], 0, -0.05, 0.88, K.ceramic, inner)
    elif t in ('mirror', 'mirror_round'):
        if t == 'mirror_round':
            o = cyl(0.38, 0.02, 0, 0, 0, K.mirror, inner, 64)
            o.rotation_euler = (math.pi / 2, 0, 0)
            o.location = (0, by - 0.02, Z + 0.4)
        else:
            B(W, 0.02, H, 0, by - 0.01, Z, K.mirror, 0)
    elif t == 'bath':
        B(W, D, 0.56, 0, 0, 0, K.ceramic, 0.02, 3)
    elif t == 'shower':
        B(W, D, 0.03, 0, 0, 0, K.ceramic, 0.004)
        if ex.get('glass') == 'blocks':
            gb = mat('glassblock', '#DDEBEE', rough=0.15, trans=0.85, coat=0.5)
            n = int(W * 0.62 / 0.195)
            for i in range(n):
                for k in range(11):
                    box(0.19, 0.08, 0.19, -W / 2 + 0.1 + i * 0.195, fy + 0.04, 0.03 + k * 0.195, gb, inner, 0.012, 2)
        else:
            B(W * 0.6, 0.008, 2.0, -W * 0.2, fy, 0.03, K.glass, 0)
            B(0.02, 0.02, 2.0, W * 0.1, fy, 0.03, K.metal, 0.002)
        # тропический душ и смеситель на боковой стене
        cyl(0.13, 0.01, 0, 0.1, 2.15, K.metal, inner, 32)
        box(0.05, 0.05, 0.25, W / 2 - 0.03, 0.1, 1.0, K.metal, inner, 0.01)
        box(0.3, 0.1, 0.02, W / 2 - 0.05, by - 0.2, 1.3, K.ceramic, inner, 0.004)
    elif t == 'loft':
        pass
    else:
        B(W, D, max(H, 0.05), 0, 0, Z, K.white, 0.003)


# ----------------------------------------------------------- декор стилей ---
def qvevri(x, y, scale, K, root):
    prof = [(0.0, 0.0), (0.05, 0.0), (0.12, 0.05), (0.22, 0.18), (0.27, 0.36), (0.26, 0.52), (0.2, 0.66),
            (0.12, 0.74), (0.1, 0.78), (0.12, 0.8), (0.11, 0.82), (0.08, 0.81), (0.0, 0.8)]
    prof = [(r * scale, h * scale) for r, h in prof]
    lathe(prof, x, y, 0.0, K.terracotta, root, 48, 'qvevri')


def olive(x, y, K, root, h=1.7, seed=3):
    random.seed(seed)
    lathe([(0, 0), (0.17, 0), (0.2, 0.42), (0.18, 0.42), (0.16, 0.06), (0, 0.06)], x, y, 0, K.pot, root, 40)
    cyl(0.02, h - 0.7, x, y, 0.4, K.trunk, root, 10)
    for i in range(700):
        a = random.uniform(0, math.tau)
        r = random.uniform(0.02, 0.5) ** 0.8
        zz = random.uniform(h - 0.85, h + 0.1)
        o = sphere(0.04, x + math.cos(a) * r * 0.9, y + math.sin(a) * r * 0.9, zz, K.leaf, root, (1.0, 0.3, 0.06), 1)
        o.rotation_euler = (random.uniform(0, 3), random.uniform(0, 3), random.uniform(0, 3))


def pendant(x, y, z_bottom, kind, K, root, color):
    sh = mat('shade_' + kind, color, rough=0.9, sss=0.3) if kind != 'globes' else K.metal
    if kind == 'drum':
        cyl(0.003, CEIL - z_bottom - 0.25, x, y, z_bottom + 0.25, K.black, root, 8)
        lathe([(0.25, 0), (0.25, 0.25), (0.245, 0.25), (0.245, 0.002)], x, y, z_bottom, sh, root, 64)
        sphere(0.05, x, y, z_bottom + 0.12, emissive('bulb', '#FFD9A8', 25), root)
    elif kind == 'paper':
        cyl(0.003, CEIL - z_bottom - 0.5, x, y, z_bottom + 0.5, K.black, root, 8)
        sphere(0.25, x, y, z_bottom + 0.25, emissive('paperlamp', '#FFE8C8', 3.0), root, sub=3)
    else:
        cyl(0.006, CEIL - z_bottom - 0.1, x, y, z_bottom + 0.1, K.metal, root, 8)
        for i in range(3):
            a = i / 3 * math.tau
            cyl(0.006, 0.18, x + math.cos(a) * 0.09, y + math.sin(a) * 0.09, z_bottom + 0.08, K.metal, root, 8)
            sphere(0.09, x + math.cos(a) * 0.16, y + math.sin(a) * 0.16, z_bottom + 0.05,
                   emissive('opal', '#FFE6C4', 6.0), root, sub=3)
    L = bpy.data.lights.new('pend', 'POINT')
    L.energy = 35
    L.color = (1.0, 0.82, 0.62)
    L.shadow_soft_size = 0.12
    o = bpy.data.objects.new('pend', L)
    o.location = (x, y, z_bottom - 0.05)
    link(o)


def wall_art(p0, p1, z0, z1, img, K, root, frame=0.02, depth=0.03, framed=True, toward=None):
    """Картина на стене: p0→p1 вдоль стены (Blender XY), лицо смотрит влево от направления
    (или в сторону точки toward)."""
    (x0, y0), (x1, y1) = p0, p1
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    nx, ny = -dy / L, dx / L
    if toward is not None and (toward[0] - (x0 + x1) / 2) * nx + (toward[1] - (y0 + y1) / 2) * ny < 0:
        (x0, y0), (x1, y1) = (x1, y1), (x0, y0)
        dx, dy, nx, ny = -dx, -dy, -nx, -ny
    m = mat('art_' + os.path.basename(img), tex=img, coords='UV', rough=0.8)
    off = depth + 0.002
    quad((x0 + nx * off, y0 + ny * off, z0), (x1 + nx * off, y1 + ny * off, z0), (x1 + nx * off, y1 + ny * off, z1),
         (x0 + nx * off, y0 + ny * off, z1), m, root)
    if framed:
        cx, cy = (x0 + x1) / 2 + nx * depth / 2, (y0 + y1) / 2 + ny * depth / 2
        g = empty('frame', cx, cy, math.atan2(dy, dx), root)
        fm = K.black if K.S['metal'] == '#2B2A28' else K.metal
        box(L + frame * 2, depth, frame, 0, 0, z0 - frame, fm, g, 0.002)
        box(L + frame * 2, depth, frame, 0, 0, z1, fm, g, 0.002)
        box(frame, depth, z1 - z0, -L / 2 - frame / 2, 0, z0, fm, g, 0.002)
        box(frame, depth, z1 - z0, L / 2 + frame / 2, 0, z0, fm, g, 0.002)


def carved_panel(p0, p1, z0, z1, K, root):
    """Джапанди: дубовая панель с вырезанными буквами асомтаврули."""
    (x0, y0), (x1, y1) = p0, p1
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    g = empty('carved', (x0 + x1) / 2, (y0 + y1) / 2, math.atan2(dy, dx), root)
    box(L, 0.03, z1 - z0, 0, -0.015, z0, K.wood, g, 0.004)
    font = bpy.data.fonts.load(TX.FONT_SERIF, check_existing=True)
    letters = TX.ASOMTAVRULI
    cols, rows = 7, 4
    for i in range(cols * rows):
        cu = bpy.data.curves.new('ch', 'FONT')
        cu.body = letters[i % len(letters)]
        cu.font = font
        cu.size = min((z1 - z0) / rows, L / cols) * 0.62
        cu.extrude = 0.004
        cu.align_x = 'CENTER'
        cu.align_y = 'CENTER'
        o = bpy.data.objects.new('ch', cu)
        o.data.materials.append(mat('carvedink', '#6E5233', rough=0.7))
        o.parent = g
        o.rotation_euler = (math.pi / 2, 0, 0)
        o.location = (-L / 2 + (i % cols + .5) * L / cols, -0.034, z1 - (i // cols + .5) * (z1 - z0) / rows)
        link(o)


def curtains(a, b, inward, K, root, width=0.5):
    """Две портьеры по краям окна (Blender XY), волна складок."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    ux, uy = dx / L, dy / L
    nx, ny = inward
    for side in (0, 1):
        verts, faces = [], []
        n = 28
        for i in range(n + 1):
            t = i / n
            s = (t * width) if side == 0 else (L - width + t * width)
            s -= 0.12 if side == 0 else -0.12
            off = 0.16 + 0.035 * math.sin(t * math.pi * 7)
            px_, py_ = x0 + ux * s + nx * off, y0 + uy * s + ny * off
            verts.append((px_, py_, 0.01))
            verts.append((px_, py_, CEIL - 0.04))
        for i in range(n):
            faces.append((2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1))
        mesh_obj('curtain', verts, faces, K.curtain, root, smooth=True)


# ----------------------------------------------------------------- сцена ---
def thickness_at(walls_u, a, b, end, along_sign):
    """Толщина стены у конца проёма: перпендикуляр через точку чуть за краем."""
    (ax, ay), (bx, by) = a, b
    L = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / L, (by - ay) / L
    px, py = (end[0] + ux * along_sign * 60, end[1] + uy * along_sign * 60)
    ln = LineString([(px - uy * 600, py + ux * 600), (px + uy * 600, py - ux * 600)])
    inter = ln.intersection(walls_u)
    if inter.is_empty:
        return None
    return inter


def build(variant, style_key, K):
    data = json.load(open(os.path.join(ROOT, 'data', 'project.json')))
    v = next(x for x in data['variants'] if x['id'] == variant)
    S = STYLES[style_key]
    root = empty('ROOT', 0, 0, 0)
    rooms_u = unary_union([Polygon(r['poly']) for r in v['rooms']])
    # полы
    for r in v['rooms']:
        p = Polygon(r['poly']).buffer(60, join_style=2).simplify(5)
        if p.geom_type != 'Polygon':
            p = max(p.geoms, key=lambda g: g.area)
        extrude(p, -0.02, 0.0, K.bath_floor if r['floor'] == 'tile' else K.floor, 'floor')
    # потолок
    ceil = rooms_u.buffer(400, join_style=2)
    for p in ([ceil] if ceil.geom_type == 'Polygon' else ceil.geoms):
        extrude(p, CEIL, CEIL + 0.05, K.ceiling, 'ceiling')
    # стены
    all_walls = []
    for k in ('mono', 'gas', 'new', 'gkl'):
        for p in polys(v['walls'][k]):
            extrude(p, 0.0, CEIL, K.wall, 'wall_' + k)
            all_walls.append(p)
    walls_u = unary_union(all_walls)
    # плинтус-тень (теневой профиль) не делаем: минимализм
    # окна
    for w in data['windows']:
        a, b = w['a'], w['b']
        ln = LineString([a, b])
        band = ln.buffer(220, cap_style=2)
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        nx, ny = -dy / L, dx / L
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        inside = 1 if rooms_u.contains(Point(mid[0] + nx * 500, mid[1] + ny * 500)) else -1
        inx, iny = nx * inside, ny * inside
        top = min(w['h'] / 1000 + 0.05, CEIL - 0.06)
        A, Bp = P(*a), P(*b)
        gx, gy = (A[0] + Bp[0]) / 2, (A[1] + Bp[1]) / 2
        rot = math.atan2(Bp[1] - A[1], Bp[0] - A[0])
        Lm = L / 1000
        g = empty('win', gx, gy, rot, root)
        box(Lm + 0.02, 0.34, CEIL - top, 0, 0, top, K.wall, g, 0)
        box(Lm + 0.02, 0.34, 0.04, 0, 0, 0, K.wall, g, 0)
        box(Lm, 0.006, top - 0.04, 0, 0, 0.04, K.glass, g, 0)
        n = max(1, round(Lm / 1.05))
        for i in range(n + 1):
            box(0.05, 0.07, top - 0.04, -Lm / 2 + i * Lm / n, 0, 0.04, K.frame, g, 0.002)
        box(Lm, 0.07, 0.05, 0, 0, 0.04, K.frame, g, 0.002)
        box(Lm, 0.07, 0.05, 0, 0, top - 0.05, K.frame, g, 0.002)
        # конвектор у окна
        bnx, bny = inx, -iny   # в осях Blender
        ix, iy = gx + bnx * 0.32, gy + bny * 0.32
        gr = empty('rad', ix, iy, rot, root)
        box(1.4, 0.08, 0.27, 0, 0, 0.015, K.white, gr, 0.004)
        # шторы
        curtains(A, Bp, (bnx, bny), K, root)
        # портал для света
        Ld = bpy.data.lights.new('portal', 'AREA')
        Ld.shape = 'RECTANGLE'
        Ld.size, Ld.size_y = Lm, top
        try:
            Ld.cycles.is_portal = True
        except Exception:
            Ld.is_portal = True
        lo = bpy.data.objects.new('portal', Ld)
        lo.location = (gx + bnx * 0.05, gy + bny * 0.05, top / 2)
        lo.rotation_euler = (math.pi / 2, 0, rot)
        # свет порталу нужно смотреть внутрь: −Z локально → по нормали внутрь
        lo.rotation_euler = (0, 0, 0)
        d = Vector((bnx, bny, 0))
        lo.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
        link(lo)
    # двери: перемычки и полотна
    for d in v['doors']:
        a, b = d['a'], d['b']
        A, Bp = P(*a), P(*b)
        Lm = math.hypot(Bp[0] - A[0], Bp[1] - A[1])
        rot = math.atan2(Bp[1] - A[1], Bp[0] - A[0])
        gx, gy = (A[0] + Bp[0]) / 2, (A[1] + Bp[1]) / 2
        # толщина стены у проёма
        th = 0.12
        probe = LineString([(a[0] + (b[0] - a[0]) * 0.5 + (b[1] - a[1]) / Lm * 0.0, 0), (0, 0)])
        g = empty('door', gx, gy, rot, root)
        H = d['h'] / 1000
        box(Lm + 0.02, th + 0.02, CEIL - H, 0, 0, H, K.wall, g, 0)
        if d['kind'] == 'mirror':
            box(Lm * 0.95, 0.03, H - 0.01, 0, 0, 0.005, K.mirror, g, 0.002)
        else:
            box(Lm - 0.02, 0.04, H - 0.02, 0, 0, 0.01, K.white if style_key != 'mix' else K.wall, g, 0.003)
            box(0.12, 0.02, 0.02, Lm / 2 - 0.12, -0.035, 1.0, K.metal, g, 0.004)
    # входная дверь
    a, b = data['entrance']['a'], data['entrance']['b']
    A, Bp = P(*a), P(*b)
    Lm = math.hypot(Bp[0] - A[0], Bp[1] - A[1])
    g = empty('entr', (A[0] + Bp[0]) / 2, (A[1] + Bp[1]) / 2, math.atan2(Bp[1] - A[1], Bp[0] - A[0]), root)
    box(Lm, 0.08, 2.14, 0, 0, 0, K.wood, g, 0.004)
    box(Lm + 0.02, 0.3, CEIL - 2.14, 0, 0, 2.14, K.wall, g, 0)
    # мебель
    for f in v['furniture']:
        build_item(f, K, root)
    return v, data


def decorate(variant, style_key, K, v):
    """Декор и грузинские акценты для кухни-гостиной (варианты A и B)."""
    S = K.S
    root = empty('DECOR', 0, 0, 0)
    tex = TEX
    # кувшин-квеври у окна, у простенка
    qvevri(*P(6450, 450) if variant == 'B' else P(6900, 3300), 0.95, K, root)
    # олива в углу у закруглённого окна
    olive(*P(9950, 700), K, root)
    # подвесы над столом (стол вдоль кухни, ось в повёрнутой системе)
    from math import cos, sin, radians
    c, s = cos(radians(43.75)), sin(radians(43.75))
    for vv in (-5.6, -4.75):
        uu = 7.8
        x, y = (uu * c - vv * s) * 1000, (uu * s + vv * c) * 1000
        pendant(*P(x, y), 1.62, S['pendant'], K, root, S['pendant_color'])
    # точечные светильники в потолке всех помещений (сетка ~1,5 м)
    spots = []
    for r in v['rooms']:
        pg = Polygon(r['poly'])
        inner = pg.buffer(-450)
        minx, miny, maxx, maxy = pg.bounds
        pts = []
        yy = miny + 700
        while yy < maxy:
            xx = minx + 700
            while xx < maxx:
                if inner.contains(Point(xx, yy)):
                    pts.append((xx, yy, r['floor']))
                xx += 1500
            yy += 1500
        if not pts:
            c = pg.representative_point()
            pts = [(c.x, c.y, r['floor'])]
        spots += pts
    for (x, y, fl) in spots:
        L = bpy.data.lights.new('spot', 'SPOT')
        L.energy = 40 if fl == 'tile' else 26
        L.spot_size = math.radians(70)
        L.spot_blend = 0.6
        L.color = (1.0, 0.84, 0.66)
        L.shadow_soft_size = 0.03
        o = bpy.data.objects.new('spot', L)
        o.location = (*P(x, y), CEIL - 0.03)
        link(o)
        cyl(0.04, 0.005, *P(x, y), CEIL - 0.006, emissive('dl', '#FFE6C8', 4), root, 24)
    # грузинский акцент на стене за оттоманкой / над буфетом
    wall_x = 6020 if variant == 'B' else 6600
    col_x = 6612  # лицо колонны в варианте B (ТВ на ней)
    for kind in S['art']:
        if kind[0] == 'poster':
            p = os.path.join(tex, f'poster_{style_key}.png')
            TX.alphabet_poster(p, kind[1], kind[2], kind[3])
            wall_art(P(wall_x + 3, 420), P(wall_x + 3, 1480), 1.2, 2.6, p, K, root)
            if variant == 'B':
                wall_art(P(col_x, 2050), P(col_x, 2750), 2.05, 2.95, p, K, root)
        elif kind[0] == 'carved':
            carved_panel(P(wall_x + 3, 1700), P(wall_x + 3, 300), 1.2, 2.3, K, root)
            if variant == 'B':
                carved_panel(P(col_x, 2980), P(col_x, 1820), 2.0, 3.0, K, root)
        elif kind[0] == 'mural':
            p = os.path.join(tex, f'mural_{style_key}.png')
            TX.alphabet_mural(p, kind[1], kind[2])
            wall_art(P(wall_x + 1, 0), P(wall_x + 1, 3720), 0.0, CEIL - 0.001, p, K, root, framed=False, depth=0.0)
            if variant == 'B':
                wall_art(P(col_x, 1800), P(col_x, 3000), 0.85, CEIL - 0.001, p, K, root, framed=False, depth=0.0)
        elif kind[0] == 'mountains':
            p = os.path.join(tex, f'mount_{style_key}.png')
            TX.art(p, list(kind[1:]), kind='mountains')
            # над диваном вдоль окна нельзя (окно) — на торце буфета у холла
            wall_art(P(6640, 3760), P(7700, 3760), 1.1, 2.4, p, K, root) if variant == 'A' else None
    # ковёр в гостиной
    rk = S['rug']
    rp = os.path.join(tex, f'rug_{rk[0]}_{rk[1][1:]}.png')
    if not os.path.exists(rp):
        TX.rug(rp, rk[1], rk[2], rk[3], kind=rk[0])
    rm = mat('rug_' + rp, tex=rp, coords='UV', rough=1.0, sheen=0.5)
    x0, y0 = P(6700, 1150)
    x1, y1 = P(8700, 2950)
    quad((x0, y1, 0.006), (x1, y1, 0.006), (x1, y0, 0.006), (x0, y0, 0.006), rm, root)
    decorate_rooms(variant, style_key, K, v, root)
    # вазы и книги на буфете
    if variant == 'B':
        bx, by = P(6320, 3400)
        lathe([(0, 0), (0.06, 0), (0.09, 0.12), (0.05, 0.3), (0.03, 0.34), (0, 0.34)], bx, by + 0.1, 0.88, K.terracotta,
              root)


def R2N(u, vv):
    c, s = math.cos(math.radians(43.75)), math.sin(math.radians(43.75))
    return (u * c - vv * s) * 1000, (u * s + vv * c) * 1000


def decorate_rooms(variant, style_key, K, v, root):
    """Спальни, детская, санузлы: плитка на стенах, картины, детская азбука."""
    S = K.S
    # плитка на стенах санузлов (в мастер-санузле до 1,2 м, выше покраска)
    door_cuts = unary_union([LineString([d['a'], d['b']]).buffer(260, cap_style=2) for d in v['doors']])
    if S['bath_wall'] == 'zellige':
        tile_m = K.zellige
    else:
        tw = os.path.join(TEX, f'bathwall_{style_key}.png')
        if not os.path.exists(tw):
            TX.tile(tw, S['bath_wall'], '#CFC8BD', tile_w=0.3, tile_h=0.6, var=0.02)
        tile_m = mat('bathwall_' + style_key, tex=tw, size=2.4, rough=0.2, coat=0.3)
    for r in v['rooms']:
        if r['floor'] != 'tile':
            continue
        pg = Polygon(r['poly'])
        c = pg.representative_point()
        La = bpy.data.lights.new('bathlight', 'AREA')
        La.size = 0.6
        La.energy = 120
        La.color = (1.0, 0.9, 0.8)
        lo = bpy.data.objects.new('bathlight', La)
        lo.location = (*P(c.x, c.y), CEIL - 0.05)
        link(lo)
        ring = pg.buffer(30, join_style=2).difference(pg.buffer(-12, join_style=2)).difference(door_cuts)
        H = 1.2 if r['name'] == 'Мастер-санузел' else 2.2
        for pr in ([ring] if ring.geom_type == 'Polygon' else ring.geoms):
            if pr.area > 1000:
                extrude(pr, 0.0, H, tile_m, 'tilewall')
    rooms = {r['name']: r for r in v['rooms']}

    def at(name):
        r = rooms.get(name)
        return P(*r['label']) if r else None
    # картина над кроватью в мастер-спальне — горы (силуэт Кавказа)
    mp = os.path.join(TEX, f'mount_{style_key}.png')
    TX.art(mp, ['#EFE7DA', '#C9A04A', '#A65A3C', '#2F4A3F', '#5A1F2A'], kind='mountains')
    if at('Мастер-спальня'):
        a, b = P(*R2N(16.73, -4.95)), P(*R2N(16.73, -3.85))
        wall_art(a, b, 1.35, 2.35, mp, K, root, toward=at('Мастер-спальня'))
    # детская: азбука мхедрули над шкафчиками с игрушками
    kp = os.path.join(TEX, f'kids_{style_key}.png')
    TX.alphabet_poster(kp, '#F6F1E7', '#2F4A3F', '#A65A3C', letters='mkhedruli')
    if at('Детская'):
        a, b = P(*R2N(10.29, -5.9)), P(*R2N(10.29, -4.5))
        wall_art(a, b, 1.15, 2.45, kp, K, root, toward=at('Детская'))
    # комнаты Майи и Вари: по картине над изголовьем / у стола
    ap_ = os.path.join(TEX, f'arches_{style_key}.png')
    TX.art(ap_, ['#EFE7DA', '#A65A3C', '#C9A04A', '#2F4A3F'], kind='arches')
    if at('Комната Вари'):
        wall_art(P(2600, 3640), P(1300, 3640), 1.3, 2.3, ap_, K, root, toward=at('Комната Вари'))
    if at('Комната Майи'):
        x = 5915 if variant == 'B' else 6395
        wall_art(P(x, 1900), P(x, 3000), 1.25, 2.15, mp, K, root, toward=at('Комната Майи'))
    # прихожая: квеври и коврик
    qvevri(*P(4600, 4600), 0.6, K, root)


def world_and_render(args, sun_from):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = args.samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = 'OPENIMAGEDENOISE'
    except Exception:
        pass
    sc.cycles.max_bounces = 8
    sc.cycles.diffuse_bounces = 4
    sc.cycles.glossy_bounces = 3
    sc.cycles.transmission_bounces = 8
    sc.cycles.transparent_max_bounces = 16
    sc.cycles.sample_clamp_indirect = 8.0
    sc.cycles.blur_glossy = 1.0
    w, h = map(int, args.res.split('x'))
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = 'AgX'
    try:
        sc.view_settings.look = 'AgX - Medium High Contrast'
    except Exception:
        pass
    sc.view_settings.exposure = args.exposure
    wd = bpy.data.worlds.new('W')
    sc.world = wd
    wd.use_nodes = True
    nt = wd.node_tree
    bg = nt.nodes['Background']
    sky = nt.nodes.new('ShaderNodeTexSky')
    sky.sky_type = 'MULTIPLE_SCATTERING'
    elev, az = sun_from
    try:
        sky.sun_elevation = math.radians(elev)
        sky.sun_rotation = math.radians(az)
        sky.altitude = 40
    except Exception:
        pass
    nt.links.new(sky.outputs['Color'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 0.22
    sun = bpy.data.lights.new('sun', 'SUN')
    sun.energy = 2.0
    sun.angle = math.radians(1.5)
    sun.color = (1.0, 0.96, 0.91)
    so = bpy.data.objects.new('sun', sun)
    so.rotation_euler = (math.radians(90 - elev), 0, math.radians(az + 90))
    link(so)
    # земля далеко внизу и силуэты города
    g = bpy.data.meshes.new('ground')
    s = 800
    g.from_pydata([(-s, -s, -28), (s, -s, -28), (s, s, -28), (-s, s, -28)], [], [(0, 1, 2, 3)])
    go = bpy.data.objects.new('ground', g)
    go.data.materials.append(mat('groundm', '#8C8F86', rough=1))
    link(go)
    random.seed(5)
    bm = mat('bld', '#C9C7C2', rough=0.9)
    for i in range(0):
        a = random.uniform(0, math.tau)
        r = random.uniform(350, 900)
        box(random.uniform(20, 50), random.uniform(20, 50), random.uniform(15, 75), 8 + math.cos(a) * r,
            -6 + math.sin(a) * r, -28, bm, None, 0)


VIEWS = {
    # cam (мм плана), target (мм плана), высота камеры, фокусное
    'kl_entry': dict(cam=(8100, 5150), tgt=(7200, 800), z=1.45, lens=16),
    'kl_window': dict(cam=(11000, 1800), tgt=(6400, 3300), z=1.45, lens=16),
    'kl_kitchen': dict(cam=(7250, 2750), tgt=(11200, 2400), z=1.45, lens=16),
    'master': dict(cam=(11670, 7985), tgt=(15233, 7660), z=1.45, lens=16),
    'kids': dict(cam=(10008, 4874), tgt=(13408, 5083), z=1.35, lens=15),
    'master_bath': dict(cam=R2N(15.3, -1.75), tgt=R2N(15.95, 2.4), z=1.5, lens=13, exp=0.8),
    'bath2': dict(cam=R2N(12.55, -1.55), tgt=R2N(12.75, 2.3), z=1.5, lens=13, exp=0.8),
    'kids2': dict(cam=(R2N(12.4, -4.0)), tgt=(R2N(10.3, -5.6)), z=1.35, lens=15),
    'maya': dict(cam=(4300, 3500), tgt=(5100, 500), z=1.45, lens=15),
    'varya': dict(cam=(2900, 3450), tgt=(1000, 500), z=1.45, lens=15),
    'bath3': dict(cam=(1700, 4150), tgt=(500, 6700), z=1.5, lens=14, exp=0.8),
    'entry': dict(cam=(5150, 6550), tgt=(5900, 3000), z=1.5, lens=15, exp=0.2),
}


def camera(view):
    V = VIEWS[view]
    cx, cy = P(*V['cam'])
    tx, ty = P(*V['tgt'])
    cam = bpy.data.cameras.new('cam')
    cam.lens = V['lens']
    cam.sensor_width = 36
    cam.clip_start = 0.05
    co = bpy.data.objects.new('cam', cam)
    co.location = (cx, cy, V['z'])
    d = Vector((tx - cx, ty - cy, 0)).normalized()
    co.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    cam.shift_y = 0.03
    link(co)
    bpy.context.scene.camera = co


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--variant', default='B')
    ap.add_argument('--style', default='warm')
    ap.add_argument('--view', default='kl_entry')
    ap.add_argument('--out', default=os.path.join(ROOT, 'renders', 'out.png'))
    ap.add_argument('--samples', type=int, default=128)
    ap.add_argument('--res', default='1600x1000')
    ap.add_argument('--exposure', type=float, default=-0.6)
    ap.add_argument('--blend', default='')
    args = ap.parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    global COLL
    COLL = bpy.context.scene.collection
    random.seed(1)
    K = Kit(STYLES[args.style], args.style)
    v, data = build(args.variant, args.style, K)
    decorate(args.variant, args.style, K, v)
    args.exposure += VIEWS[args.view].get('exp', 0.0)
    world_and_render(args, sun_from=(28, 35))
    camera(args.view)
    if args.blend:
        bpy.ops.wm.save_as_mainfile(filepath=args.blend)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.context.scene.render.filepath = args.out
    bpy.ops.render.render(write_still=True)
    print('saved', args.out)


if __name__ == '__main__':
    main()
