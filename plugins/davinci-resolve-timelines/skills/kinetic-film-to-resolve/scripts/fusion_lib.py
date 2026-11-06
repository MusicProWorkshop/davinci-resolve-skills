# fusion_lib.py: builds kinetic-type shots as real, editable Fusion comps. Runs inside Resolve's scripting host.
# Layout numbers are in the kinetic engine's 1920x1080 space and frame counts are at 60 fps; both scale to the timeline.
import math, os, re, shutil

C = dict(W=1920, H=1080, FPS=60.0, BPM=120.0, FONT='Lato', STYLE='Black', UI_FONT='Inter', UI_STYLE='Medium', PX=1249.0, EM={}, PAL={})
PLACE = -32768

def beat(k): return int(round(k * 60.0 / C['BPM'] * C['FPS']))
def fr(n): return int(round(n * C['FPS'] / 60.0))
def clamp(u): return max(0.0, min(1.0, u))
def out_expo(u): return 1.0 if u >= 1 else 1 - 2 ** (-10 * u)
def in_expo(u): return 0.0 if u <= 0 else 2 ** (10 * (u - 1))
def out_cubic(u): return 1 - (1 - u) ** 3
def lerp(a, b, u): return a + (b - a) * u
def elastic(u): return 1.0 if u >= 1 else 0.0 if u <= 0 else 2 ** (-10 * u) * math.sin((u * 10 - .75) * 2.0944) + 1

def pal(c, fallback='paper'):
    """A colour as an 8-bit tuple, from a palette name, #hex or rgb()/rgba()."""
    if isinstance(c, (tuple, list)): return tuple(c[:3])
    c = c or fallback
    c = C['PAL'].get(c, c)
    m = re.match(r'#([0-9a-fA-F]{6})', c)
    if m: return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    m = re.match(r'#([0-9a-fA-F]{3})$', c)
    if m: return tuple(int(x * 2, 16) for x in m.group(1))
    m = re.match(r'rgba?\((\d+)\D+(\d+)\D+(\d+)', c)
    if m: return tuple(int(x) for x in m.groups())
    return pal(fallback) if c != fallback else (255, 255, 255)

def lum(c): return (.2126 * c[0] + .7152 * c[1] + .0722 * c[2]) / 255.0
def readable(g): return pal('ink') if lum(g) > .42 else pal('paper')
def rgb(c): return tuple(v / 255.0 for v in c)
def mix(a, b, u): return tuple(int(lerp(a[n], b[n], u)) for n in range(3))

def em(word):
    """A word's width in ems: measured for the chosen font when em.json exists, otherwise a fair estimate."""
    if word in C['EM']: return C['EM'][word]
    return sum(.3 if ch in "Ii.,:;'!| " else .95 if ch in 'MWmw' else .6 if ch.islower() else .7 for ch in word) or 1.0

def fit(word, px): return min(px / (em(word) * C['PX']), 450.0 / C['PX'])   # fill the width, but never taller than the frame allows
def wanted(word, size=None, px=1500): return min(1640, em(word) * size) if size else px

def key(tool, name, pts):
    tool.AddModifier(name, 'BezierSpline')
    if pts[0][0] > 0: pts = [(0, pts[0][1])] + pts   # AddModifier leaves a stray key at frame 0: pin it to the first value
    for f, v in pts: tool.SetInput(name, v, f)

def key_xy(tool, name, pts):
    tool.AddModifier(name, 'XYPath')
    mod = tool[name].GetConnectedOutput().GetTool()
    mod.AddModifier('X', 'BezierSpline'); mod.AddModifier('Y', 'BezierSpline')
    if pts[0][0] > 0: pts = [(0, pts[0][1])] + pts
    for f, (x, y) in pts:
        mod.SetInput('X', x, f); mod.SetInput('Y', y, f)

def bake(f0, f1, a, b, ease=out_expo, step=1):
    n = max(1, int((f1 - f0) / step))
    return [(f0 + (f1 - f0) * i / float(n), lerp(a, b, ease(i / float(n)))) for i in range(n + 1)]

class Shot:
    def __init__(self, comp, dur, ground='bg'):
        self.c, self.dur = comp, dur   # never comp.Lock() here: Resolve then outputs black for the clip
        self.ground = pal(ground, 'bg')
        m = comp.FindToolByID('MediaIn')
        if m: m.Delete()
        self.bg = self.solid(self.ground, name='Ground')
        self.top = self.solid((0, 0, 0), a=0.0, name='Stage')

    def ink(self): return readable(self.ground)

    def solid(self, col, w=1920, h=1080, a=1.0, name=None):
        t = self.c.AddTool('Background', PLACE, PLACE)
        t.SetInput('UseFrameFormatSettings', 0)
        t.SetInput('Width', max(1, int(w * C['W'] / 1920.0))); t.SetInput('Height', max(1, int(h * C['H'] / 1080.0)))
        r, g, b = rgb(col)
        t.SetInput('TopLeftRed', r * a); t.SetInput('TopLeftGreen', g * a); t.SetInput('TopLeftBlue', b * a); t.SetInput('TopLeftAlpha', a)
        if name: t.SetAttrs({'TOOLS_Name': name})
        return t

    def merge(self, fg, center=None, blend=None, name=None):
        m = self.c.AddTool('Merge', PLACE, PLACE)
        m.ConnectInput('Background', self.top); m.ConnectInput('Foreground', fg)
        if center: m.SetInput('Center', {1: center[0], 2: center[1], 3: 0})
        if blend is not None: m.SetInput('Blend', blend)
        if name: m.SetAttrs({'TOOLS_Name': name})
        self.top = m
        return m

    def text(self, s, size, col=None, outline=0, tracking=1.0, ui=False, name=None):
        t = self.c.AddTool('TextPlus', PLACE, PLACE)
        t.SetInput('UseFrameFormatSettings', 0); t.SetInput('Width', C['W']); t.SetInput('Height', C['H'])
        t.SetInput('StyledText', s); t.SetInput('Font', C['UI_FONT'] if ui else C['FONT']); t.SetInput('Style', C['UI_STYLE'] if ui else C['STYLE'])
        t.SetInput('Size', size); t.SetInput('CharacterSpacing', tracking)
        r, g, b = rgb(col if col else self.ink())
        if outline:
            t.SetInput('Enabled1', 0); t.SetInput('Enabled2', 1)
            t.SetInput('Red2', r); t.SetInput('Green2', g); t.SetInput('Blue2', b)
            t.SetInput('Thickness2', .012); t.SetInput('Alpha2', 1.0)
        else:
            t.SetInput('Red1', r); t.SetInput('Green1', g); t.SetInput('Blue1', b)
        if name: t.SetAttrs({'TOOLS_Name': name})
        return t

    def xf(self, src, blur=False, name=None):
        x = self.c.AddTool('Transform', PLACE, PLACE)
        x.ConnectInput('Input', src)
        if blur:
            x.SetInput('MotionBlur', 1); x.SetInput('Quality', 5); x.SetInput('ShutterAngle', 240)
        if name: x.SetAttrs({'TOOLS_Name': name})
        return x

    def loader(self, path, name=None):
        path = path.replace('\\', '/')
        stem, ext = os.path.splitext(os.path.basename(path))
        if stem[-1:].isdigit():  # Fusion reads key1.png, key2.png as one image sequence, so give each still a name that cannot be one
            copy = os.path.join(C['ASSETS'], stem + '_still' + ext).replace('\\', '/')
            os.makedirs(C['ASSETS'], exist_ok=True)
            if not os.path.exists(copy) or os.path.getmtime(copy) < os.path.getmtime(path): shutil.copyfile(path, copy)
            path = copy
        self.c.Lock()            # unlocked, setting a Loader's clip opens a modal file picker that blocks all scripting
        l = self.c.AddTool('Loader', PLACE, PLACE)
        l.Clip[1] = path
        l.Loop[1] = 1            # a still must keep showing past its single frame
        self.c.Unlock()          # only around the Loader: a comp left locked, or wired while locked, renders black
        if name: l.SetAttrs({'TOOLS_Name': name})
        return l

    # ---- type moves ----
    def word(self, s, size, f0=0, y=.5, x=.5, col=None, s0=1.7, rot=0.0, settle=10, drift=.05, name=None):
        """A word that slams in at frame f0, settles, then keeps growing slowly."""
        t = self.text(s, size, col, name=name or 'Word')
        m = self.xf(t, name='Move')
        m.SetInput('Angle', rot)
        pts = bake(f0, f0 + fr(settle), s0, 1.0) + [(self.dur, 1.0 + drift)]
        if f0 > 0: pts = [(f0 - 1, 0.001)] + pts
        key(m, 'Size', pts)
        self.merge(m, center=(x, y), name='Place')
        return m

    def ghosts(self, s, size, col=None, rows=(.2, .8), alpha=.2, travel=.1):
        c = mix(self.ground, col or self.ink(), alpha)
        for i, y in enumerate(rows):
            g = self.text(s, size, c, outline=1, name='GhostRow')
            m = self.xf(g, name='GhostMove')
            d = travel if i % 2 == 0 else -travel
            key_xy(m, 'Center', [(0, (.5 - d, .5)), (self.dur, (.5 + d, .5))])
            self.merge(m, center=(.5, y), name='GhostPlace')

    def rect(self, col, cx, cy, w, h, radius=0.0, name=None):
        """A full-frame solid cut by a rectangle mask. Sizes in 1920x1080 pixels; returns (mask, merge)."""
        b = self.solid(col, name=name or 'Rect')
        r = self.c.AddTool('RectangleMask', PLACE, PLACE)
        r.SetInput('Center', {1: cx, 2: cy, 3: 0}); r.SetInput('Width', w / 1920.0); r.SetInput('Height', h / 1080.0)
        if radius: r.SetInput('CornerRadius', radius)
        b.ConnectInput('EffectMask', r)
        return r, self.merge(b, name=(name or 'Rect') + 'Add')

    def bar(self, px, y, f0, col, x=.5, h=26, grow=14):
        left = x - px / 2.0 / 1920
        r, _ = self.rect(col, left, y, 0, h, name='Bar')
        pts = bake(f0, f0 + fr(grow), 0.0, 1.0)
        key(r, 'Width', [(f, u * px / 1920.0) for f, u in pts])
        key_xy(r, 'Center', [(f, (left + u * px / 1920.0 / 2, y)) for f, u in pts])

    def camera(self, push=.09, zoom=.9, pan=30, d=1, whip_in=None, whip_out=None, hits=(), wf=8, blur=True, exit=None):
        """Everything so far is the stage; move it with one camera and lay it over the ground. exit = (frame, final scale)."""
        wf = fr(wf)
        hl = fr(13)
        c = self.xf(self.top, blur=bool(blur), name='Camera')
        frames = set(range(0, self.dur + 1, fr(6))) | {self.dur}
        if whip_in: frames |= set(range(0, wf + 1))
        if whip_out: frames |= set(range(self.dur - wf, self.dur + 1))
        if exit: frames |= set(range(exit[0], self.dur + 1))
        for f0, _ in hits: frames |= {f for f in range(f0, f0 + hl) if f <= self.dur}
        xy, sz = [], []
        for f in sorted(x for x in frames if x >= 0):
            st, x, y, s = f / C['FPS'], 0.0, 0.0, zoom + push * f / C['FPS']
            x += d * pan * st / 1920
            if whip_in and f <= wf:
                k = 1 - out_expo(f / float(wf)); x += whip_in[0] * k; y += whip_in[1] * k
            if whip_out and f >= self.dur - wf:
                k = in_expo((f - (self.dur - wf)) / float(wf)); x += whip_out[0] * k; y += whip_out[1] * k
            for f0, amp in hits:
                if f0 <= f < f0 + hl:
                    u = (f - f0) / float(hl); dec = (1 - u) ** 2
                    x += amp * dec * math.sin(f * 2.7) / 1920; y += amp * dec * math.cos(f * 3.3) / 1080
                    s *= 1 + .05 * dec
            if exit and f >= exit[0]:
                s *= lerp(1.0, exit[1], in_expo((f - exit[0]) / float(max(1, self.dur - exit[0]))))
            xy.append((f, (.5 + x, .5 + y))); sz.append((f, s))
        key_xy(c, 'Center', xy); key(c, 'Size', sz)
        if blur:
            # blur re-renders the whole stage per sample, so switch it on only for the fast moves, where it shows
            on = set()
            if whip_in: on |= set(range(0, wf + 1))
            if whip_out: on |= set(range(self.dur - wf - 1, self.dur + 1))
            if exit: on |= set(range(exit[0], self.dur + 1))
            if blur != 'whips':
                for f0, _ in hits: on |= set(range(f0, min(f0 + fr(6), self.dur + 1)))
            key(c, 'MotionBlur', [(f, 1 if f in on else 0) for f in range(0, self.dur + 1) if f in on or f - 1 in on or f + 1 in on or f == 0])
        self.top = self.bg
        self.merge(c, name='OverGround')

    # ---- full-frame effects, added after camera() ----
    def flash(self, f0, col=(255, 255, 255), a=.85, n=7):
        m = self.merge(self.solid(col, name='FlashColor'), name='Flash')
        key(m, 'Blend', ([(f0 - 1, 0.0)] if f0 else []) + bake(f0, f0 + fr(n), a, 0.0, lambda u: u))

    def flash_out(self, f0, col=(255, 255, 255)):
        m = self.merge(self.solid(col, name='FlashColor'), name='FlashOut')
        key(m, 'Blend', [(f0, 0.0), (self.dur, 1.0)])

    def ring(self, f0, col=None, n=20, end=1.0, width=.006):
        s = self.solid(col or pal('accent'), name='RingColor')
        e = self.c.AddTool('EllipseMask', PLACE, PLACE)
        e.SetInput('Solid', 0); e.SetInput('BorderWidth', width)
        pts = bake(f0, f0 + fr(n), .02, end, out_cubic, 2)
        key(e, 'Width', pts); key(e, 'Height', pts)
        s.ConnectInput('EffectMask', e)
        m = self.merge(s, name='Ring')
        key(m, 'Blend', ([(f0 - 1, 0.0)] if f0 else []) + [(f0, 1.0), (f0 + fr(n) * .5, 1.0), (f0 + fr(n), 0.0)])

    def rays(self, f0, col=None, n=26, a=.55):
        """Radial speed lines: thin lines rotated around the centre, with a hole that opens outward."""
        col = col or self.ink()
        base = self.solid((0, 0, 0), a=0.0, name='RayStage')
        thin = self.solid(col, w=3200, h=2, name='RayThin'); thick = self.solid(col, w=3200, h=4, name='RayThick')
        for i in range(13):
            d = self.c.AddTool('Merge', PLACE, PLACE)
            d.ConnectInput('Background', base); d.ConnectInput('Foreground', thick if i % 3 == 0 else thin)
            d.SetInput('Angle', i * 13.85 + 7 * math.sin(i * 2.3))
            base = d
        e = self.c.AddTool('EllipseMask', PLACE, PLACE)
        e.SetInput('Invert', 1); e.SetInput('SoftEdge', .05)
        pts = bake(f0, f0 + fr(n), .22, 1.5, out_cubic, 3)
        key(e, 'Width', pts); key(e, 'Height', pts)
        base.ConnectInput('EffectMask', e)
        m = self.merge(base, name='Rays')
        key(m, 'Blend', [(f0, a), (f0 + fr(n), 0.0)] if f0 == 0 else [(f0 - 1, 0.0), (f0, a), (f0 + fr(n), 0.0)])

    def glow(self, amount=.9, size=18):
        g = self.c.AddTool('SoftGlow', PLACE, PLACE)
        g.ConnectInput('Input', self.top); g.SetInput('Threshold', .55); g.SetInput('Gain', amount); g.SetInput('XGlowSize', size)
        self.top = g

    def slash(self, f0):
        b = self.solid(pal('hot'), w=2600, h=9, name='SlashLine')
        m = self.merge(b, name='Slash')
        m.SetInput('Angle', -28)
        key_xy(m, 'Center', [(f0 - 1, (-1.0, .5)), (f0 + fr(6), (.5, .5)), (f0 + fr(12), (2.0, .5))])

    def finish(self):
        self.c.FindToolByID('MediaOut').ConnectInput('Input', self.top)

def _fx(s, fx, f0, big=False):
    """The hit a shot lands on: punch = rays, ring, flash; hit = flash; beat or none add no layers."""
    if fx == 'punch':
        s.rays(f0); s.flash(f0, a=.6 if big else .5); s.ring(f0)
    elif fx == 'hit':
        s.flash(f0, a=.45)

# ---- the shot styles ----
def cut(s, word, size=None, rot=0.0, col=None, y=.5, whip_in=None, whip_out=None, d=1, fx='beat', big=False, flash_at=None, exit=None):
    sz = fit(word, wanted(word, size))
    s.ghosts(word, sz, pal(col) if col else None, alpha=.18)
    s.word(word, sz, col=pal(col) if col else None, s0=1.12, rot=rot, y=y, settle=7)
    s.camera(zoom=.92, push=.1, d=d, hits=[(0, 12)], whip_in=whip_in, whip_out=whip_out, exit=exit)
    _fx(s, fx, 0, big)
    if flash_at is not None: s.flash_out(flash_at)

def slam(s, word, size=None, col=None, whip_in=None, whip_out=None, d=1, fx='hit', big=False, flash_at=None, exit=None):
    sz = fit(word, wanted(word, size))
    s.ghosts(word, sz, pal(col) if col else None, alpha=.2)
    s.word(word, sz, col=pal(col) if col else None, s0=1.9, settle=9)
    s.camera(zoom=.92, push=.1, d=d, hits=[(0, 18)], whip_in=whip_in, whip_out=whip_out, exit=exit)
    _fx(s, fx, 0, big)
    if flash_at is not None: s.flash_out(flash_at)

def punch(s, word, f0=0, col=None, whip_in=None, whip_out=None, charge=False, flash_at=None, exit=None):
    sz = fit(word, wanted(word))
    s.word(word, sz, f0=f0, s0=.15, settle=11, col=pal(col) if col else None)
    s.camera(zoom=.92, push=.08, hits=[(f0, 24)], whip_in=whip_in, whip_out=whip_out, exit=exit)
    if charge: s.rays(0, a=.5, n=f0 / C['FPS'] * 60 + 30)
    else: s.rays(f0)
    s.flash(f0, a=.6); s.ring(f0)
    if flash_at is not None: s.flash_out(flash_at)

def stack(s, kicker, word, px=1620, y=.47, whip_in=None, whip_out=None, d=1, col=None, fx='none', second=.5, flash_at=None, exit=None):
    sz = fit(word, px); ks = min(fit(kicker, px * .62), sz * .46)
    half = beat(second)
    e, ke = sz * C['PX'], ks * C['PX']
    ky = y + (e * .53 + ke * .47) / 1080
    actual = em(word) * e
    c = pal(col) if col else None
    s.word(kicker, ks, y=ky, s0=1.25, settle=8, drift=.02, col=c, name='Kicker')
    s.word(word, sz, f0=half, y=y, s0=1.7, settle=9, drift=.04, col=c)
    s.bar(actual, y - e * .54 / 1080, half + beat(.3), pal('accent') if lum(s.ground) < .42 or s.ground[0] > 240 and s.ground[2] > 200 else pal('ink'))
    s.camera(zoom=.92, push=.08, d=d, whip_in=whip_in, whip_out=whip_out, hits=[(half, 12)], exit=exit)
    _fx(s, fx, half)
    if flash_at is not None: s.flash_out(flash_at)

def pair(s, a, b, whip_in=None, whip_out=None, d=1, fx='beat', second=.5, flash_at=None, exit=None):
    """Two lines that arrive from opposite sides."""
    sz = min(fit(a, 1560), fit(b, 1560))
    half = beat(second)
    e = sz * C['PX']
    for line, y, f0, side in ((a, .5 + e * .46 / 1080, 0, -1), (b, .5 - e * .46 / 1080, half, 1)):
        t = s.text(line, sz, name='Line'); m = s.xf(t, name='LineSlide')
        pts = [(f, (x, .5)) for f, x in bake(f0, f0 + fr(12), .5 + side * 1.1, .5)]
        if f0: pts = [(f0 - 1, (.5 + side * 2, .5))] + pts
        key_xy(m, 'Center', pts + [(s.dur, (.5 + side * .012, .5))])
        s.merge(m, center=(.5, y), name='LinePlace')
    s.camera(zoom=.92, push=.08, d=d, whip_in=whip_in, whip_out=whip_out, hits=[(half, 12)], exit=exit)
    _fx(s, fx, half)
    if flash_at is not None: s.flash_out(flash_at)

def split(s, small, big, px=1560, col='accent', whip_in=None, whip_out=None, d=1, fx='punch', second=.5, heavy=False, flash_at=None, exit=None):
    sz = min(fit(big, px), 420.0 / C['PX']); ss = sz * .42
    half = beat(second)
    e = sz * C['PX']; w = em(big) * e
    s.word(small, ss, y=.5 + e * .5 / 1080, x=.5 - (w - em(small) * ss * C['PX']) / 2 / 1920, s0=1.2, settle=7, drift=.02, name='Small')
    c = pal(col)
    if abs(lum(c) - lum(s.ground)) < .2: c = s.ink()      # the accent word has to stand out on this ground
    t = s.text(big, sz, c, name='Big')
    m = s.xf(t, name='BigSlide')
    key_xy(m, 'Center', [(half - 1, (1.6, .5))] + [(f, (x, .5)) for f, x in bake(half, half + fr(10), 1.25, .5)] + [(s.dur, (.485, .5))])
    s.merge(m, center=(.5, .47), name='Place')
    s.camera(zoom=.92, push=.09, d=d, whip_in=whip_in, whip_out=whip_out, hits=[(half, 24)], exit=exit)
    if lum(s.ground) < .42: s.glow(.5)
    _fx(s, fx, half, heavy)
    if flash_at is not None: s.flash_out(flash_at)

def typed(s, text, label=None, size=.075, whip_in=None, whip_out=None, start=.1, end=.85, flash_at=None, ui=True):
    """Text that types itself on, with an optional small label above it."""
    t = s.text(text, size, name='Typed', ui=ui)
    key(t, 'End', [(s.dur * start, 0.0), (s.dur * end, 1.0)])
    s.merge(t, name='TypedPlace')
    if label:
        s.merge(s.text(label, .032, pal('accent'), ui=True, name='Label'), center=(.5, .84), name='LabelPlace')
    s.camera(zoom=1.0, push=.04, pan=12, whip_in=whip_in, whip_out=whip_out)
    if flash_at is not None: s.flash_out(flash_at, pal('accent'))

# ---- Strike ----
def _rects(s, rects):
    for x, y, w, h, c in rects:
        s.merge(s.solid(c, w=w, h=h, name='Block'), center=(x, y), name='Add')

def _grey(s): return mix(s.ground, s.ink(), .22)
def _panel(s): return mix(s.ground, s.ink(), .08)

def mock_timeline(s, die, ui):
    rows = [(.62, [(.27, 240), (.46, 200), (.66, 300)]), (.53, [(.31, 340), (.56, 170), (.72, 180)]), (.44, [(.26, 180), (.43, 260), (.66, 320)]), (.35, [(.33, 380), (.62, 280)])]
    rects = [(.5, .5, 1300, 420, _panel(s))]
    for n, (y, clips) in enumerate(rows):
        for i, (x, w) in enumerate(clips):
            rects.append((x, y, w, 62, pal('accent') if (n + i) % 4 == 1 else _grey(s)))
    rects.append((.8, .5, 4, 420, pal('accent')))
    _rects(s, rects)
    if ui.get('title'): s.merge(s.text(ui['title'], .022, s.ink(), ui=True), center=(.27, .7))
    if ui.get('tag'): s.merge(s.text(ui['tag'], .022, pal('accent'), ui=True), center=(.74, .7))

def mock_tiles(s, die, ui):
    tiles = ui.get('tiles') or []
    for i, tile in enumerate(tiles):
        label = tile[0]; sub = tile[2] if len(tile) > 2 else ''
        x = (i + 1.0) / (len(tiles) + 1)
        keep = s.top; s.top = s.solid((0, 0, 0), a=0.0, name='Tile')
        s.merge(s.solid((255, 255, 255), w=340, h=214, name='Card'), name='CardAdd')
        s.merge(s.text(label, min(.066, fit(label, 280)), pal('ink')), center=(.5, .52))
        if sub: s.merge(s.text(sub, .018, (0x6B, 0x75, 0x80), ui=True), center=(.5, .43))
        m = s.xf(s.top, name='TileFall'); s.top = keep
        t0 = die + i * fr(2)
        key_xy(m, 'Center', [(0, (.5, .5)), (t0, (.5, .5)), (t0 + fr(14), (.5, -.3))])
        key(m, 'Angle', [(0, -1.5 + i), (t0, -1.5 + i), (t0 + fr(14), 34 - 18 * i)])
        s.merge(m, center=(x, .5), name='TilePlace')

def mock_rack(s, die, ui):
    rows = ui.get('rows') or ['NODE 01', 'NODE 02', 'NODE 03']
    for j, label in enumerate(rows):
        y = .64 - j * (.28 / max(1, len(rows) - 1))
        _rects(s, [(.5, y, 1240, 110, _panel(s))])
        s.merge(s.text(label, .017, mix(s.ground, s.ink(), .65), ui=True), center=(.25, y))
        strip = s.text(' '.join(['■'] * 14), .02, pal('accent') if j == 1 else s.ink(), ui=True, tracking=1.4, name='Lights')   # one text per row, not 14 layers
        key(strip, 'End', [(die + j * fr(3), 1.0), (die + j * fr(3) + fr(16), 0.0)])
        s.merge(strip, center=(.6, y), name='LightsAdd')

MOCKS = {'timeline': mock_timeline, 'tiles': mock_tiles, 'rack': mock_rack}

def strike(s, word, ui=None, no='NO', whip_in=None, whip_out=None, tv_off=False):
    """NO + a word over a mock of the old way, which dies on its beat. Stay under about 2.5 beats per item at slow tempos."""
    b1, b15, b2 = beat(1), beat(1.5), beat(2)
    mock = MOCKS.get((ui or {}).get('type'))
    if mock:
        keep = s.top; s.top = s.solid((0, 0, 0), a=0.0, name='UI')
        mock(s, b2, ui)
        panel = s.xf(s.top, name='MockMove')
        panel.SetInput('Angle', -2.0)
        key(panel, 'Size', bake(0, fr(12), 1.2, 1.0) + [(s.dur, 1.04)])
        key(panel, 'Blend', [(b2 + fr(2), 1.0), (b2 + fr(12), 0.0)])
        s.top = keep
        s.merge(panel, center=(.5, .38), name='MockPlace')
    gap, target = 90, 1680
    n = 1 + em(no) / max(.01, em(word))
    px = min(1300, (target - gap) / n)
    sz = fit(word, px); w = em(word) * sz * C['PX']; nw = em(no) * sz * C['PX']
    total = nw + gap + w
    y = .76 if mock else .5
    s.word(no, sz, f0=b1, x=.5 - (total - nw) / 2 / 1920, y=y, col=pal('accent'), s0=1.8, settle=8, drift=.03, name='No')
    s.word(word, sz, f0=b15, x=.5 + (total - w) / 2 / 1920, y=y, s0=1.5, settle=8, drift=.03)
    s.camera(zoom=.95, push=.06, pan=26, whip_in=whip_in, whip_out=whip_out, hits=[(b1, 10), (b2, 14)], blur='whips', exit=(s.dur - fr(10), .02) if tv_off else None)
    if (ui or {}).get('type') == 'timeline': s.slash(b2)

# ---- Stretch ----
def stretch(s, word, grounds=None, px=1480, whip_in=None, whip_out=None):
    """An elastic word: squeezes and overshoots on the beat, the ground flipping as the spec says. Without a variable font this is scale, not width axis."""
    sz = fit(word, px); d = s.dur
    k = lambda rel: rel * d / 8.0
    gr = [(a, pal(g)) for a, g in (grounds or [[0, 'accent'], [4, 'paper'], [5, 'accent']])]
    first = readable(gr[0][1])
    s.ghosts(word, sz * .92, first, rows=(.72, .28), alpha=.2, travel=.22)
    t = s.text(word, sz, first, name='Word')
    m = s.xf(t, name='Elastic')
    m.SetInput('UseSizeAndAspect', 0)
    xs = [(f, lerp(.52, 1.0, elastic((f - k(1)) / (k(3) - k(1))))) for f in range(int(k(1)), int(k(3)) + 1)]
    xs += [(k(4), 1.0)] + [(f, lerp(1.0, .56, out_expo((f - k(4)) / (k(4.8) - k(4))))) for f in range(int(k(4)) + 1, int(k(4.8)) + 1)]
    xs += [(k(5), .56)] + [(f, lerp(.56, 1.02, elastic((f - k(5)) / (k(7) - k(5))))) for f in range(int(k(5)) + 1, int(k(7)) + 1)] + [(d, 1.04)]
    key(m, 'XSize', [(0, .52)] + xs)
    key(m, 'YSize', bake(0, fr(9), 1.5, 1.0) + [(d, 1.05)])
    s.merge(m, center=(.5, .54), name='Place')
    s.bar(px, .36, k(1), first, h=4)
    hits = [(0, 18)] + [(int(k(a)), 12) for a, _ in gr[1:]]
    s.camera(zoom=.92, push=.1, pan=14, hits=hits, whip_in=whip_in, whip_out=whip_out)
    if len(gr) > 1:
        for i, (name, tn) in enumerate((('TopLeftRed', 'Red1'), ('TopLeftGreen', 'Green1'), ('TopLeftBlue', 'Blue1'))):
            pts, tpts = [(0, gr[0][1][i] / 255.0)], [(0, first[i] / 255.0)]
            for j in range(1, len(gr)):
                f = int(k(gr[j][0]))
                pts += [(f - 1, gr[j - 1][1][i] / 255.0), (f, gr[j][1][i] / 255.0)]
                a, b = readable(gr[j - 1][1]), readable(gr[j][1])
                tpts += [(f - 1, a[i] / 255.0), (f, b[i] / 255.0)]
            key(s.bg, name, pts); key(t, tn, tpts)
    s.flash(0, a=.6)

# ---- real 3D ----
def _t3(s, word, size, col, z=0.0, depth=.07, name=None):
    t = s.c.AddTool('Text3D', PLACE, PLACE)
    t.SetInput('StyledText', word); t.SetInput('Font', C['FONT']); t.SetInput('Style', C['STYLE']); t.SetInput('Size', size)
    t.SetInput('ExtrusionDepth', depth)       # keep it shallow: deep extrusions blur the letter shapes
    r, g, b = rgb(col)
    t.SetInput('Red1', r); t.SetInput('Green1', g); t.SetInput('Blue1', b)
    t.SetInput('Transform3DOp.Translate.Z', z)
    if name: t.SetAttrs({'TOOLS_Name': name})
    return t

def _scene3d(s, parts, cam):
    m = s.c.AddTool('Merge3D', PLACE, PLACE)
    m.ConnectInput('SceneInput1', cam)
    for i, p in enumerate(parts): m.ConnectInput('SceneInput%d' % (i + 2), p)
    n = len(parts) + 2
    amb = s.c.AddTool('LightAmbient', PLACE, PLACE); amb.SetInput('Intensity', .5)
    sun = s.c.AddTool('LightDirectional', PLACE, PLACE); sun.SetInput('Intensity', .85)
    sun.SetInput('Transform3DOp.Rotate.X', -35); sun.SetInput('Transform3DOp.Rotate.Y', 25)
    m.ConnectInput('SceneInput%d' % n, amb); m.ConnectInput('SceneInput%d' % (n + 1), sun)
    r = s.c.AddTool('Renderer3D', PLACE, PLACE)
    r.ConnectInput('SceneInput', m); r.SetInput('LightingEnabled', 1)
    r.SetInput('UseFrameFormatSettings', 0); r.SetInput('Width', C['W']); r.SetInput('Height', C['H'])
    r.SetInput('MotionBlur', 1); r.SetInput('Quality', 5); r.SetInput('ShutterAngle', 200)
    s.merge(r, name='Render3D')

def fly(s, words, whip_in=None, whip_out=None):
    """Extruded words in depth: the camera holds on each, rushes through it to the next and lands on the last."""
    gap, d, n = 12.0, s.dur, len(words)
    span = d * (n - .35) / float(n)
    per = span / max(1.0, n - 1.0)
    parts = []
    for i, (w, c) in enumerate(words):
        size = fit(w, 1500) * 1.3
        t = _t3(s, w, size, pal(c), z=-gap * i, name='Word3D')
        if i: key(t, 'Size', [(per * (i - 1) + per * .3 - 1, .0001), (per * (i - 1) + per * .3, size)])
        parts.append(t)
    cam = s.c.AddTool('Camera3D', PLACE, PLACE); cam.SetAttrs({'TOOLS_Name': 'FlyCam'})
    zs, xs, rz = [], [], []
    for f in range(0, d + 1, 2):
        pos = min(f / span, 1.0) * (n - 1)
        i = min(int(pos), max(0, n - 2)); frac = pos - i
        eased = frac ** 3 * (frac * (6 * frac - 15) + 10)   # hold near each word, rush between them
        zs.append((f, 2.4 - gap * (i + eased) - .1 * f / C['FPS']))
        xs.append((f, .12 * math.sin(f * .045 * 60 / C['FPS'])))
        rz.append((f, 4 * math.sin(f * .03 * 60 / C['FPS'])))
    key(cam, 'Transform3DOp.Translate.Z', zs); key(cam, 'Transform3DOp.Translate.X', xs); key(cam, 'Transform3DOp.Rotate.Z', rz)
    _scene3d(s, parts, cam)
    s.camera(zoom=1.0, push=.0, pan=0, blur=False, whip_in=whip_in, whip_out=whip_out)
    s.glow(.35, 12)

def hero(s, kicker, title, sub=None, whip_in=None, whip_out=None):
    """The kicker lands, an extruded 3D title flies out of depth and turns, and a line types under it."""
    d, land = s.dur, beat(1.0)
    ep = min(1385.0 / em(title), 300.0)        # the title's on-screen em in pixels; .738 is measured for this camera
    t = _t3(s, title, ep / (C['PX'] * .738), s.ink(), name='Title3D')
    key(t, 'Transform3DOp.Rotate.Y', [(land - 1, -55)] + bake(land, land + fr(22), -55, -12) + [(d, 14)])
    key(t, 'Transform3DOp.Translate.Z', [(0, -60), (land - 1, -60)] + bake(land, land + fr(14), -60, 0) + [(d, .22)])
    cam = s.c.AddTool('Camera3D', PLACE, PLACE); cam.SetInput('Transform3DOp.Translate.Z', 2.4); cam.SetAttrs({'TOOLS_Name': 'HeroCam'})
    _scene3d(s, [t], cam)
    if kicker:
        kem = min(fit(kicker, 980) * C['PX'], ep * .5)
        s.word(kicker, kem / C['PX'], y=min(.88, .5 + (ep + kem * .55) / 1080.0), s0=1.3, settle=9, drift=.03, name='Kicker')
    if sub:
        t2 = s.text(sub, .036, pal('accent'), ui=True, name='Typed')
        w0 = beat(2.4)
        key(t2, 'End', [(w0, 0.0), (min(d - 1, w0 + beat(2.2)), 1.0)])
        s.merge(t2, center=(.5, .24), name='TypedPlace')
    s.camera(zoom=.9, push=.09, pan=30, whip_in=whip_in, whip_out=whip_out, hits=[(land, 22)], blur=False)
    s.rays(land, a=.45); s.flash(land, a=.55); s.ring(land, n=24)

# ---- Picture ----
def picture(s, src, words=(), cutIns=(), tint=.25, focus=(.5, .5), x=None, y=None, reveal='slash', whip_in=None, whip_out=None):
    """Key art that pushes and pans, punches in on every word and hard-cuts in to details."""
    d = s.dur
    l = s.loader(src, name='Art')
    a = l.GetAttrs(); iw = (a.get('TOOLIT_Clip_Width') or {1: 1920})[1]; ih = (a.get('TOOLIT_Clip_Height') or {1: 1080})[1]
    cover = max(C['W'] / float(iw), C['H'] / float(ih))
    keep = s.top; s.top = s.bg
    m = s.merge(l, name='ArtPlace')
    cuts = sorted((beat(c[0]), c[1], c[2] if len(c) > 2 else focus) for c in cutIns)
    sz, ctr, f = [], [], 0
    fx, fy = focus[0], 1 - focus[1]
    frames = sorted(set(list(range(0, d + 1, fr(4))) + [d] + [c[0] for c in cuts] + [c[0] - 1 for c in cuts if c[0] > 0] + [beat(w[0]) for w in words] + [beat(w[0]) + fr(6) for w in words]))
    for f in frames:
        if f < 0 or f > d: continue
        zoom, cx, cy = 1.04 + .1 * f / float(d), .5 + (.5 - fx) * .06 * f / float(d), .5 + (.5 - fy) * .06 * f / float(d)
        for w in words:
            bf = beat(w[0])
            if bf <= f < bf + fr(6): zoom *= 1 + .05 * (1 - (f - bf) / float(fr(6)))
        for cf, cs, cfocus in cuts:
            if cf <= f < cf + beat(1.5):
                zoom *= cs; cx = .5 + (.5 - cfocus[0]) * cs; cy = .5 + (cfocus[1] - .5) * cs
        room = max(0.0, (zoom - 1) / 2.0)   # how far the art can slide before an edge shows
        cx, cy = max(.5 - room, min(.5 + room, cx)), max(.5 - room, min(.5 + room, cy))
        sz.append((f, cover * zoom)); ctr.append((f, (cx, cy)))
    key(m, 'Size', sz); key_xy(m, 'Center', ctr)
    if tint: s.merge(s.solid((0, 0, 0), name='Tint'), blend=tint, name='TintAdd')
    art = s.top; s.top = keep
    for w in words:
        t, txt = beat(w[0]), w[1]
        nxt = [beat(o[0]) for o in words if o[0] > w[0]]
        col = pal(w[2]) if len(w) > 2 else pal('paper')
        wx = x or 960
        tool = s.word(txt, fit(txt, min(1200, 2 * (min(wx, 1920 - wx) - 70))), f0=t, x=wx / 1920.0, y=1 - (y or 540) / 1080.0, col=col, s0=1.5, settle=7, drift=.03)
        if nxt:
            pl = s.top
            key(pl, 'Blend', [(nxt[0] - 1, 1.0), (nxt[0], 0.0)])
    stage = s.top
    s.bg, s.top = art, stage
    s.camera(zoom=1.0, push=.02, pan=0, whip_in=whip_in, whip_out=whip_out, hits=[(c[0], 10) for c in cuts], blur='whips')

# ---- Logo ----
def logo(s, tagline=None, small=None, wordmark=None, assets=None, width=840, y=.54, **_):
    """The end card: a line and a hit, the mark pieces drop in, the name wipes on, the lines follow, then a slow push."""
    line = s.solid(pal('hot'), w=1240, h=5, name='HitLine')
    lm = s.xf(line, name='HitGrow')
    lm.SetInput('UseSizeAndAspect', 0)
    key(lm, 'XSize', bake(0, fr(10), 0.0, 1.0)); key(lm, 'YSize', bake(fr(10), fr(24), 1.0, 0.0))
    s.merge(lm, center=(.5, y), name='HitPlace')
    scale = C['W'] / 1920.0 / 2.0   # the PNGs are drawn at twice the logo's width
    f1 = fr(40)
    if assets:
        for i, p in enumerate(assets['marks']):
            f0 = fr(12) + i * fr(5)
            m = s.merge(s.loader(p, name='Mark%d' % (i + 1)), name='MarkAdd%d' % (i + 1))
            m.SetInput('Size', scale)
            key_xy(m, 'Center', [(f0 - 1, (.5, 1.6))] + [(f, (.5, yy)) for f, yy in bake(f0, f0 + fr(12), 1.1, y)])
        word = assets.get('word') or (assets['all'] if not assets['marks'] else None)
        if word:
            n = s.loader(word, name='LogoWord')
            e = s.c.AddTool('RectangleMask', PLACE, PLACE)
            e.SetInput('Center', {1: 0, 2: .5, 3: 0}); e.SetInput('Height', 1.0)
            key(e, 'Width', bake(f1, f1 + fr(26), 0.0, 2.2, out_cubic, 2))
            n.ConnectInput('EffectMask', e)
            m = s.merge(n, center=(.5, y), name='WordAdd'); m.SetInput('Size', scale)
        h = assets['height'] * scale * 1080.0 / C['H']
    else:
        name = wordmark or ''
        t = s.text(name, fit(name, 1400), s.ink(), name='Wordmark')
        e = s.c.AddTool('RectangleMask', PLACE, PLACE)
        e.SetInput('Center', {1: 0, 2: .5, 3: 0}); e.SetInput('Height', 1.0)
        key(e, 'Width', bake(fr(12), fr(38), 0.0, 2.2, out_cubic, 2))
        t.ConnectInput('EffectMask', e)
        s.merge(t, center=(.5, y), name='WordmarkPlace')
        h = fit(name, 1400) * C['PX']
    drop = (h / 2.0 + 58) / 1080.0
    if tagline:
        m = s.merge(s.text(tagline, min(.042, fit(tagline, 1500)), mix(s.ground, s.ink(), .9), ui=True, name='Tagline'), center=(.5, y - drop), name='TaglinePlace')
        key(m, 'Blend', [(fr(74), 0.0), (fr(86), 1.0)])
    if small:
        m = s.merge(s.text(small, min(.019, fit(small, 1600) * .9), mix(s.ground, s.ink(), .6), ui=True, tracking=1.25, name='Small'), center=(.5, y - drop - .07), name='SmallPlace')
        key(m, 'Blend', [(fr(92), 0.0), (fr(104), 1.0)])
    s.camera(zoom=1.0, push=.018, pan=0, hits=[(fr(12), 12)])
    s.flash(0, col=pal('hot'), a=.7)
    if lum(s.ground) < .42: s.glow(.25, 22)
