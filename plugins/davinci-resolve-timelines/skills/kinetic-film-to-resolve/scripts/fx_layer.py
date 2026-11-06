# fx_layer.py: the kinetic engine's effects layer, rebuilt in Fusion from the list export_film.mjs writes to film.json.
# Comets, spark bursts, slashes, drifting lights, the charge-up, invert flashes and the dot grid are drawn in the shot
# where they happen, at the engine's own timing and positions. The shot styles already draw their own hit rays, rings
# and flashes, so those are not repeated here.
import math, os, subprocess

def _xy(x, y): return (x / 1920.0, 1 - y / 1080.0)

def rng(seed):
    """The engine's xorshift generator, so sparks and rays fall at the same angles as in the original."""
    st = [((int(seed) * 2654435761) & 0xFFFFFFFF) or 1]
    def nxt():
        x = st[0]
        x ^= (x << 13) & 0xFFFFFFFF; x ^= x >> 17; x ^= (x << 5) & 0xFFFFFFFF
        st[0] = x & 0xFFFFFFFF
        return st[0] / 4294967296.0
    return nxt
def _in_cubic(u): return u ** 3

def _spot(s, col, r, soft=.04, a=1.0):
    """A soft round spot of radius r (1920x1080 pixels) in the middle of a full-frame transparent image."""
    b = s.solid(col, a=a, name='SpotColor')
    e = s.c.AddTool('EllipseMask', PLACE, PLACE)
    e.SetInput('Width', 2 * r / 1920.0); e.SetInput('Height', 2 * r / 1920.0); e.SetInput('SoftEdge', soft)   # ellipse masks size both axes by the frame width
    b.ConnectInput('EffectMask', e)
    return b

def _over(s, layer, mode='Screen', name=None):
    m = s.merge(layer, name=name)
    m.SetInput('ApplyMode', mode)
    return m

def _local(t, f0): return int(round(t * C['FPS'])) - f0

def comet(s, c, f0, tint):
    """A glowing head running along the engine's sampled path, trailing a stroke that drains into it on arrival."""
    pts, src = c['pts'], 60.0
    t0, t1 = c['t0'], c['t1']
    tail = c.get('tail', .14); hold = c.get('hold') or 0; fade = c.get('fade', .08)
    fa, fb = _local(t0, f0), _local(t1, f0)
    end = fb + int(round((max(tail, hold) + fade) * C['FPS']))
    if end < 0 or fa > s.dur: return False
    size, col = c.get('size', 9), pal(c.get('color') or 'accent')
    # the stroke follows the path sampled evenly along itself (240 steps), so it stays a smooth curve even where the
    # eased comet moves fast; the per-frame samples only say how far along the path the head is at each moment
    P = c.get('path') or pts
    us = c.get('us') or [i / max(1.0, len(pts) - 1.0) for i in range(len(pts))]
    L = [0.0]
    for i in range(1, len(P)): L.append(L[-1] + math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]))
    tot = max(1e-6, L[-1])
    def u_at(t):
        i = max(0.0, min(len(us) - 1.0, (t - t0) * src)); j = min(len(us) - 1, int(i)); k = min(len(us) - 1, j + 1)
        return lerp(us[j], us[k], i - j)
    def along(u):
        i = max(0.0, min(1.0, u)) * (len(P) - 1); j = min(len(P) - 1, int(i)); k = min(len(P) - 1, j + 1)
        return i - j, j, k
    def at(t):
        """Arc length along the path at time t."""
        w, j, k = along(u_at(t)); return lerp(L[j], L[k], w)
    def head_xy(t):
        w, j, k = along(u_at(t)); return (lerp(P[j][0], P[k][0], w), lerp(P[j][1], P[k][1], w))
    poly = {'Closed': False, 'Points': {n + 1: {'X': x / 1920.0 - .5, 'Y': .5 - y / 1080.0, 'LX': 0, 'LY': 0, 'RX': 0, 'RY': 0, 'Linear': True} for n, (x, y) in enumerate(P)}}
    wp, wl, hp, ha = [], [], [], []
    for f in range(max(0, fa - 1), min(s.dur, end) + 1):
        t = (f0 + f) / C['FPS']
        if t < t0: wl.append((f, 0.0)); ha.append((f, 0.0)); continue
        head = min(t, t1); drain = max(0.0, min(1.0, (t - t1) / tail)) if t > t1 else 0.0
        a0, a1 = at(max(t0, head - tail * (1 - drain))), at(head)
        wp.append((f, (a0 + a1) / 2 / tot)); wl.append((f, max(0.0, (a1 - a0) / tot)))
        hp.append((f, _xy(*head_xy(head))))
        after = t - t1
        ha.append((f, 1.0 if after <= hold else max(0.0, 1 - (after - hold) / fade)))
    for bw, al, cc in ((size * 1.7, .4, col), (size * .5, .95, tint)):
        bsol = s.solid(cc, name='CometStroke')
        m = s.c.AddTool('PolylineMask', PLACE, PLACE)
        m.SetInput('Polyline', poly); m.SetInput('Solid', 0); m.SetInput('BorderWidth', bw / 1920.0); m.SetInput('SoftEdge', .002 if al < .9 else 0)
        key(m, 'WritePosition', wp or [(0, 0.0)]); key(m, 'WriteLength', wl)
        bsol.ConnectInput('EffectMask', m)
        _over(s, bsol, name='CometTail').SetInput('Blend', al)
    hm = s.c.AddTool('Merge', PLACE, PLACE)
    keep_top = s.top
    s.top = s.solid((0, 0, 0), a=0.0, name='CometHeadStage')
    s.merge(_spot(s, col, size * 3.0, .05, .6), name='CometGlow'); s.merge(_spot(s, tint, size * .9, .015), name='CometCore')
    head_img = s.top; s.top = keep_top
    hm.ConnectInput('Background', s.solid((0, 0, 0), a=0.0, name='CometClear')); hm.ConnectInput('Foreground', head_img)
    if hp: key_xy(hm, 'Center', hp)
    key(hm, 'Blend', ha)
    _over(s, hm, name='CometHead')
    return True

def slash(s, sl, f0, tint):
    """A streak that shoots from one point to another and drains away behind its head."""
    fa = _local(sl['t0'], f0)
    dur, hold, fade, w = sl.get('dur', .12), sl.get('hold', .22), sl.get('fade', .2), sl.get('w', 7)
    fe = fa + int(math.ceil((dur + hold + fade) * C['FPS']))
    if fe < 0 or fa > s.dur: return False
    col = pal(sl.get('color') or 'accent')
    for lw, al, c in ((w * 2.4, .45, col), (w * .7, 1.0, tint)):
        b = s.solid(c, name='SlashColor')
        r = s.c.AddTool('RectangleMask', PLACE, PLACE); r.SetInput('Height', lw / 1080.0)
        b.ConnectInput('EffectMask', r)
        mm = _over(s, b, name='Slash')
        cs, ws, an, bl = [], [], [], []
        for f in range(max(0, fa - 1), min(s.dur, fe) + 1):
            age = (f - fa) / C['FPS']
            if age < 0: bl.append((f, 0.0)); continue
            u = 1 - (1 - min(1, age / dur)) ** 3
            tu = _in_cubic(max(0, min(1, (age - dur * .6) / (hold + fade))))
            a = 1.0 if age <= dur + hold else max(0.0, 1 - (age - dur - hold) / fade)
            hx, hy = lerp(sl['x1'], sl['x2'], u), lerp(sl['y1'], sl['y2'], u)
            tx, ty = lerp(sl['x1'], sl['x2'], tu * u), lerp(sl['y1'], sl['y2'], tu * u)
            cs.append((f, _xy((hx + tx) / 2, (hy + ty) / 2))); ws.append((f, max(.0005, math.hypot(hx - tx, hy - ty) / 1920.0)))
            an.append((f, math.degrees(math.atan2(-(hy - ty), hx - tx)))); bl.append((f, a * al))
        if not cs: continue
        key_xy(r, 'Center', cs); key(r, 'Width', ws); key(r, 'Angle', an); key(mm, 'Blend', bl)
    return True

def _emitter(s, x, y, n_at, life, speed, var=.65, angle=0.0, spread=360.0, col=None, size=.6, line=True, gravity=0.0, drag=0.0, seed=1, pre=0):
    e = s.c.AddTool('pEmitter', PLACE, PLACE)
    e.SetInput('RandomSeed', seed)
    for f, v in n_at: e.SetInput('Number', v, f) if False else None
    e.AddModifier('Number', 'BezierSpline')
    for f, v in n_at: e.SetInput('Number', v, f)
    e.SetInput('Lifespan', life); e.SetInput('LifespanVariance', life * .45)
    e.SetInput('Velocity', speed); e.SetInput('VelocityVariance', speed * var)
    e.SetInput('Angle', angle); e.SetInput('AngleVariance', spread)
    e.SetInput('SphereRgn.Size', .002); e.SetInput('SphereRgn.Translate.X', (x - 960) / 1920.0); e.SetInput('SphereRgn.Translate.Y', (540 - y) / 1920.0)
    e.SetInput('Style', 'ParticleStyleLine' if line else 'ParticleStyleBlob')
    c = rgb(col or pal('accent'))
    e.SetInput('ParticleStyle.Red', c[0]); e.SetInput('ParticleStyle.Green', c[1]); e.SetInput('ParticleStyle.Blue', c[2])
    e.SetInput('ParticleStyle.Size', size); e.SetInput('ParticleStyle.SizeVariance', size * .5)
    if line: e.SetInput('ParticleStyle.SizeToVelocity', 1.0)
    e.SetInput('ParticleStyle.FadeOut', .6)
    top = e
    if gravity:
        g = s.c.AddTool('pDirectionalForce', PLACE, PLACE); g.ConnectInput('Input', top); g.SetInput('Strength', gravity); g.SetInput('Direction', 270); top = g
    if drag:
        d = s.c.AddTool('pFriction', PLACE, PLACE); d.ConnectInput('Input', top); d.SetInput('VelocityFriction', drag); top = d
    r = s.c.AddTool('pRender', PLACE, PLACE); r.ConnectInput('Input', top)
    r.SetInput('UseFrameFormatSettings', 0); r.SetInput('Width', C['W']); r.SetInput('Height', C['H'])
    if pre: r.SetInput('PreGenerateFrames', pre)
    return r

def burst(s, b, f0):
    """Sparks thrown out from a point at the engine's own angles and speeds: they slow, fall and fade."""
    fa = _local(b['t0'], f0); life = b.get('life', .6); n = b.get('n', 26)
    fe = fa + int(math.ceil(life * C['FPS']))
    if fe < 0 or fa > s.dur: return False
    r = rng(b.get('seed', 7)); light = b.get('blend') == 'source-over'
    col = pal(b.get('color') or 'accent'); x0, y0 = b['x'], b['y']
    keep = s.top
    s.top = s.solid((0, 0, 0), a=0.0, name='SparkStage')
    dmax = 1 / 3.2   # the engine's drag: a spark ends up speed / 3.2 from where it started
    glyphs = b.get('glyphs')
    for i in range(n):
        ang = b.get('angle', 0.0) + (r() - .5) * (b['spread'] if b.get('spread') is not None else math.pi * 2)
        sp = b.get('speed', 900) * (.35 + .65 * r()); r()     # the engine also draws each spark's life here
        R, ln = sp * dmax, max(6, b.get('len', .035) * sp * .45 + 2)
        if glyphs:
            # a code glyph instead of a streak, turning as it flies
            ch = glyphs[int(r() * len(glyphs))]; spin = (r() - .5) * 2 * 2
            d = s.text(ch, b.get('gsize', 30) / C['PX'], col, ui=True, name='Glyph')
            m = s.merge(d, center=_xy(x0 + math.cos(ang) * R, y0 + math.sin(ang) * R), name='GlyphAdd')
            m.SetInput('Angle', -math.degrees(spin))
            continue
        d = s.solid(col, w=ln, h=b.get('w', 3), name='Spark')
        m = s.merge(d, center=_xy(x0 + math.cos(ang) * R, y0 + math.sin(ang) * R), name='SparkAdd')
        m.SetInput('Angle', -math.degrees(ang))
    pattern = s.top; s.top = keep
    t = s.xf(pattern, name='SparkFly')
    t.SetInput('Pivot', {1: x0 / 1920.0, 2: 1 - y0 / 1080.0, 3: 0})
    sz, ct, bl = [], [], []
    g = b.get('g', 260)
    for f in range(max(0, fa - 1), min(s.dur, fe) + 1):
        age = (f - fa) / C['FPS']
        if age < 0: sz.append((f, .001)); bl.append((f, 0.0)); continue
        sz.append((f, max(.001, (1 - math.exp(-3.2 * age)) / 3.2 / dmax)))
        ct.append((f, _xy(x0, y0 + g * age * age)))
        bl.append((f, max(0.0, 1 - age / life) * b.get('alpha', 1.0)))
    key(t, 'Size', sz)
    if ct: key_xy(t, 'Center', ct)
    m = s.merge(t, name='Sparks')
    if not light: m.SetInput('ApplyMode', 'Screen')
    key(m, 'Blend', bl)
    return True

def ray_burst(s, ro, f0):
    """Speed lines that shoot outward from a hit and drain away: a ring of lines between a fast head and a slower tail."""
    dur = ro.get('dur', .5); fa = _local(ro['t0'], f0); fe = fa + int(math.ceil(dur * C['FPS']))
    if fe < 0 or fa > s.dur: return False
    r = rng(ro.get('seed', 3)); n = min(40, ro.get('n', 64) // 2)
    col = pal(ro.get('color') or 'paper'); cx, cy = ro.get('cx', 960), ro.get('cy', 540)
    base = s.solid((0, 0, 0), a=0.0, name='RayStage')
    for i in range(n):
        a = r() * math.pi * 2; r(); r(); ww = ro.get('w', 2.4) * (.45 + 1.1 * r()); r()
        line = s.solid(col, w=3400, h=max(1, ww), name='Ray')
        d = s.c.AddTool('Merge', PLACE, PLACE); d.ConnectInput('Background', base); d.ConnectInput('Foreground', line)
        d.SetInput('Center', {1: cx / 1920.0, 2: 1 - cy / 1080.0, 3: 0}); d.SetInput('Angle', -math.degrees(a)); base = d
    outer = s.c.AddTool('EllipseMask', PLACE, PLACE); inner = s.c.AddTool('EllipseMask', PLACE, PLACE)
    for e in (outer, inner): e.SetInput('Center', {1: cx / 1920.0, 2: 1 - cy / 1080.0, 3: 0}); e.SetInput('SoftEdge', .02)
    inner.SetInput('Invert', 1); inner.SetInput('PaintMode', 'Minimum'); inner.ConnectInput('EffectMask', outer)
    r0, r1 = ro.get('r0', 60), ro.get('r1', 1400)
    oh, ih, bl = [], [], []
    for f in range(max(0, fa - 1), min(s.dur, fe) + 1):
        q = max(0.0, min(1.0, (f - fa) / max(1.0, dur * .75 * C['FPS'])))
        h = lerp(r0, r1, 1 - (1 - q) ** 3); tl_ = lerp(r0, r1, q ** 3)
        oh.append((f, h)); ih.append((f, tl_)); bl.append((f, 0.0 if f < fa else (1 - q) * ro.get('alpha', 1.0)))
    key(outer, 'Width', [(f, 2 * v / 1920.0) for f, v in oh]); key(outer, 'Height', [(f, 2 * v / 1920.0) for f, v in oh])
    key(inner, 'Width', [(f, 2 * v / 1920.0) for f, v in ih]); key(inner, 'Height', [(f, 2 * v / 1920.0) for f, v in ih])
    base.ConnectInput('EffectMask', inner)
    m = s.merge(base, name='RayBurst')
    if ro.get('blend') != 'source-over': m.SetInput('ApplyMode', 'Screen')
    key(m, 'Blend', bl)
    return True

def ring_fx(s, ro, f0):
    """An expanding shockwave ring."""
    dur = ro.get('dur', .45); fa = _local(ro['t0'], f0); fe = fa + int(math.ceil(dur * C['FPS']))
    if fe < 0 or fa > s.dur: return False
    col = pal(ro.get('color') or 'accent'); cx, cy = ro.get('cx', 960), ro.get('cy', 540)
    b = s.solid(col, name='RingColor'); e = s.c.AddTool('EllipseMask', PLACE, PLACE)
    e.SetInput('Solid', 0); e.SetInput('Center', {1: cx / 1920.0, 2: 1 - cy / 1080.0, 3: 0})
    r0, r1, w = ro.get('r0', 20), ro.get('r1', 700), ro.get('w', 10)
    ws, hs, bw, bl = [], [], [], []
    for f in range(max(0, fa - 1), min(s.dur, fe) + 1):
        k = max(0.0, min(1.0, (f - fa) / max(1.0, dur * C['FPS'])))
        rr = lerp(r0, r1, 1 - (1 - k) ** 3)
        ws.append((f, 2 * rr / 1920.0)); hs.append((f, 2 * rr * ro.get('sy', 1) / 1920.0)); bw.append((f, w * (1 - k * .8) / 1920.0))
        bl.append((f, 0.0 if f < fa else (1 - k) * ro.get('alpha', 1.0)))
    key(e, 'Width', ws); key(e, 'Height', hs); key(e, 'BorderWidth', bw)
    b.ConnectInput('EffectMask', e)
    m = s.merge(b, name='Ring')
    if ro.get('blend') != 'source-over': m.SetInput('ApplyMode', 'Screen')
    key(m, 'Blend', bl)
    return True

def flash_fx(s, fl, f0):
    """A full-frame flash in the engine's colour, rising and falling over its own timing."""
    dur, rise = fl.get('dur', .12), fl.get('rise', .01)
    fa = _local(fl['t0'], f0); fe = fa + int(math.ceil(dur * C['FPS']))
    if fe < 0 or fa > s.dur: return False
    m = s.merge(s.solid(pal(fl.get('color') or '#FFFFFF'), name='FlashColor'), name='Flash')
    pk = fl.get('peak', 1.0); fr_ = max(1, int(round(rise * C['FPS'])))
    key(m, 'Blend', [(max(0, fa - 1), 0.0), (max(0, fa + fr_), pk), (max(1, fe), 0.0)])
    return True

def bokeh(s, b, f0):
    """Points of light drifting across the frame, already in the air when they fade in."""
    fa, fb = _local(b['t0'], f0), _local(b['t1'], f0)
    if fb < 0 or fa > s.dur: return False
    vx, vy = b.get('vx', 0), b.get('vy', -30)
    sp = math.hypot(vx, vy) / C['FPS'] / 1920.0
    e = s.c.AddTool('pEmitter', PLACE, PLACE)
    e.SetInput('RandomSeed', b.get('seed', 5)); e.SetInput('Number', b.get('n', 40) / 90.0); e.SetInput('Lifespan', 300)
    e.SetInput('Velocity', sp); e.SetInput('VelocityVariance', sp * .5)
    e.SetInput('Angle', math.degrees(math.atan2(-vy, vx))); e.SetInput('AngleVariance', 25)
    e.SetInput('SphereRgn.Size', 1.3); e.SetInput('Style', 'ParticleStyleBlob')
    c = rgb(pal(b.get('color') or 'accent'))
    e.SetInput('ParticleStyle.Red', c[0]); e.SetInput('ParticleStyle.Green', c[1]); e.SetInput('ParticleStyle.Blue', c[2])
    e.SetInput('ParticleStyle.Size', .5 * b.get('size', 3) / 2.5); e.SetInput('ParticleStyle.SizeVariance', .4); e.SetInput('ParticleStyle.Blur', .4)
    r = s.c.AddTool('pRender', PLACE, PLACE); r.ConnectInput('Input', e)
    r.SetInput('UseFrameFormatSettings', 0); r.SetInput('Width', C['W']); r.SetInput('Height', C['H']); r.SetInput('PreGenerateFrames', 150)
    m = _over(s, r, name='Bokeh')
    a = b.get('alpha', .6); q = int(.25 * C['FPS'])
    key(m, 'Blend', [(max(0, fa - 1), 0.0), (max(0, fa + q), a), (min(s.dur, fb - q), a), (min(s.dur, fb), 0.0)])
    return True

def charge(s, r, f0):
    """Lines that keep converging on the centre, and a glowing point that grows, until the first word lands."""
    fa, fb = _local(r['t0'], f0), _local(r['t0'] + r.get('dur', .5), f0)
    if fb < 0 or fa > s.dur: return False
    col = pal(r.get('color') or 'accent')
    base = s.solid((0, 0, 0), a=0.0, name='ChargeStage')
    line = s.solid(col, w=3200, h=2, name='ChargeLine')
    for i in range(18):
        d = s.c.AddTool('Merge', PLACE, PLACE); d.ConnectInput('Background', base); d.ConnectInput('Foreground', line)
        d.SetInput('Angle', i * 10.7 + 6 * math.sin(i * 1.9)); base = d
    e = s.c.AddTool('EllipseMask', PLACE, PLACE); e.SetInput('Invert', 1); e.SetInput('SoftEdge', .12)
    pts = [(f, lerp(1.6, .03, (f - fa) / float(max(1, fb - fa)))) for f in range(max(0, fa), min(s.dur, fb) + 1, 2)]
    key(e, 'Width', pts); key(e, 'Height', pts)
    base.ConnectInput('EffectMask', e)
    m = _over(s, base, name='ChargeLines'); key(m, 'Blend', [(max(0, fa), .2), (max(1, fb - 2), .9), (max(2, fb), 0.0)])
    dot = s.c.AddTool('Merge', PLACE, PLACE)
    dot.ConnectInput('Background', s.solid((0, 0, 0), a=0.0, name='DotClear')); dot.ConnectInput('Foreground', _spot(s, col, 40, .06))
    key(dot, 'Size', [(f, (4 + 10 * ((f - fa) / float(max(1, fb - fa))) ** 2) / 14.0) for f in range(max(0, fa), min(s.dur, fb) + 1, 2)])
    md = _over(s, dot, name='ChargeDot'); key(md, 'Blend', [(max(0, fa), .8), (max(1, fb), 1.0), (max(2, fb + 2), 0.0)])
    return True

def invert(s, iv, f0):
    fa = _local(iv[0], f0); n = max(1, int(round(iv[1] * C['FPS'])))
    if fa + n < 0 or fa > s.dur: return False
    m = s.merge(s.solid((255, 255, 255), name='InvertWhite'), name='Invert'); m.SetInput('ApplyMode', 'Difference')
    key(m, 'Blend', [(max(0, fa - 1), 0.0), (max(0, fa), 1.0), (fa + n - 1, 1.0), (fa + n, 0.0)])
    return True

def dot_flash(s, dt, f0):
    """The engine's dot flash: a field of fine dots inside an ellipse, lit by a ring that sweeps outward."""
    dur = dt.get('dur', .6); fa = _local(dt['t0'], f0); fe = fa + int(math.ceil(dur * C['FPS']))
    if fe < 0 or fa > s.dur or not C.get('DOTS'): return False
    img = s.loader(C['DOTS'], name='DotFlash')
    cx, cy, rx, ry = dt.get('cx', 960), dt.get('cy', 540), dt.get('rx', 900), dt.get('ry', 400)
    outer = s.c.AddTool('EllipseMask', PLACE, PLACE); inner = s.c.AddTool('EllipseMask', PLACE, PLACE)
    for e in (outer, inner): e.SetInput('Center', {1: cx / 1920.0, 2: 1 - cy / 1080.0, 3: 0}); e.SetInput('SoftEdge', .06)
    inner.SetInput('Invert', 1); inner.SetInput('PaintMode', 'Minimum'); inner.ConnectInput('EffectMask', outer)
    ow, ih, bl = [], [], []
    for f in range(max(0, fa - 1), min(s.dur, fe) + 1):
        q = max(0.0, (f - fa) / max(1.0, dur * C['FPS'])) * 1.1
        ow.append((f, min(1.0, q + .3))); ih.append((f, max(0.0, q - .3)))
        bl.append((f, 0.0 if f < fa else math.sin(math.pi * min(1.0, (f - fa) / max(1.0, dur * C['FPS']))) * dt.get('alpha', .55)))
    key(outer, 'Width', [(f, 2 * rx * v / 1920.0) for f, v in ow]); key(outer, 'Height', [(f, 2 * ry * v / 1920.0) for f, v in ow])
    key(inner, 'Width', [(f, 2 * rx * v / 1920.0) for f, v in ih]); key(inner, 'Height', [(f, 2 * ry * v / 1920.0) for f, v in ih])
    img.ConnectInput('EffectMask', inner)
    m = _over(s, img, name='DotFlashAdd'); key(m, 'Blend', bl)
    return True

def dot_grid(s, png):
    """The engine's dot grid behind dark shots. It sits on the stage, so it moves with the camera."""
    if lum(s.ground) > .42: return
    s.merge(s.loader(png, name='DotGrid'), name='DotGridPlace')

def dots_png(folder):
    """A 1920x1080 transparent field of the engine's fine dots (3.2 px every 22 px), for dot flashes."""
    p = os.path.join(folder, 'dotfield.png').replace('\\', '/')
    if not os.path.exists(p):
        os.makedirs(folder, exist_ok=True)
        c = pal('paper')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x%02x%02x%02x:s=1920x1080:d=1' % c, '-vf',
                        "format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(mod(X+1,22),4)*lt(mod(Y+1,22),4),255,0)'", '-frames:v', '1', p], check=True)
    return p

def grid_png(folder):
    """A 3840x2160 transparent image of the engine's dot grid (2.6 px dots every 128 px), drawn once with ffmpeg."""
    p = os.path.join(folder, 'dotgrid.png').replace('\\', '/')
    if not os.path.exists(p):
        os.makedirs(folder, exist_ok=True)
        c = pal('paper')
        expr = "if(lt(mod(X+1984,128),3)*lt(mod(Y+1008,128),3),41,0)"
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x%02x%02x%02x:s=3840x2160:d=1' % c, '-vf',
                        "format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='%s'" % expr, '-frames:v', '1', p], check=True)
    return p

def apply_fx(s, fx, f0, notes=None):
    """Every engine effect that falls inside this shot. f0 is the shot's first frame on the timeline."""
    if not fx: return 0
    n = 0
    for c in fx.get('comets', []): n += bool(comet(s, c, f0, pal(fx.get('tint') or 'paper')))
    for sl in fx.get('slashes', []): n += bool(slash(s, sl, f0, pal(fx.get('tint') or 'paper')))
    for b in fx.get('bursts', []): n += bool(burst(s, b, f0))
    for dt in fx.get('dots', []): n += bool(dot_flash(s, dt, f0))
    for b in fx.get('bokehs', []): n += bool(bokeh(s, b, f0))
    for r in fx.get('rays', []):
        n += bool(charge(s, r, f0) if r.get('inward') else ray_burst(s, r, f0))
    for r in fx.get('rings', []): n += bool(ring_fx(s, r, f0))
    for fl in fx.get('flashes', []): n += bool(flash_fx(s, fl, f0))
    # the engine's inverts are left out: drawn as a Difference merge they turned whole frames blue, which the original never shows
    return n

def grid_on(fx, t0, t1):
    """Whether the engine draws its dot grid during this time span (some scenes, like the fly-through, switch it off)."""
    return not any(g['noGrid'] and g['t0'] < t1 and g['t1'] > t0 for g in (fx or {}).get('grid', []))
