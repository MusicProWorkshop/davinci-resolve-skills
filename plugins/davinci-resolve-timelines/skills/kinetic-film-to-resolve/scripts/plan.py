# plan.py: turns film.json into a flat list of shots. One clip per shot: an editor can then trim, reorder or open any of them.
# plan_film(film) -> (shots, notes). A shot is {name, k0, k1, ground, fn, kw}; notes list every approximation for the report.
import os

X, Y = .9, .9   # how far a whip throws the stage, as a fraction of the frame
IN = {'whipX': ((X, 0), (-X, 0)), 'whipXr': ((-X, 0), (X, 0)), 'whipY': ((0, -Y), (0, Y))}   # (next shot arrives from, previous shot leaves to)

def _tok(s, film):
    if not isinstance(s, str): return s
    secs = film.get('dur', 0); fps = film.get('fps', 60)
    return s.replace('{lines}', format(film.get('lines', 0), ',')).replace('{frames}', format(int(round(secs * fps)), ',')).replace('{seconds}', str(int(round(secs))))

def _whip(w, leaving):
    """A block's whipIn/whipOut [dx, dy, ...] in pixels, as a stage offset."""
    if not w: return None
    sx = (w[0] > 0) - (w[0] < 0); sy = (w[1] > 0) - (w[1] < 0) if len(w) > 1 else 0
    return (-sx * X, sy * Y) if leaving else (sx * X, -sy * Y)

def _name(s): return (s if isinstance(s, str) else ' '.join(s))[:32]

def _words(sc, film, notes):
    k0, k1, o = sc['k0'], sc['k1'], sc['o']
    shots = sorted(o.get('shots', []), key=lambda s: s['at'])
    ex = o.get('exit') or {}
    out = []
    for i, s in enumerate(shots):
        a = k0 if i == 0 else s['at']
        b = shots[i + 1]['at'] if i + 1 < len(shots) else k1
        st = s.get('style', 'slam'); text = s.get('text', '')
        text = [_tok(t, film) for t in text] if isinstance(text, list) else _tok(text, film)
        kw = {}
        if s.get('color'): kw['col'] = s['color']
        if s.get('in') in IN: kw['whip_in'] = IN[s['in']][0]
        if i + 1 < len(shots) and shots[i + 1].get('in') in IN: kw['whip_out'] = IN[shots[i + 1]['in']][1]
        d = -1 if i % 2 else 1
        if i == len(shots) - 1 and ex:
            at = ex.get('at', k1)
            if ex.get('type') == 'flash': kw['flash_at'] = ('beat', at - a)
            elif ex.get('type') == 'zoom':
                kw['exit'] = ('beat', at - a, 9.0); notes.append('"%s": zoom through a letter became a fast push into the word' % _name(text))
            elif ex.get('type') == 'collapse': kw['exit'] = ('beat', at - a, .002)
        fx = s.get('fx')
        if st == 'cut':
            fn = 'cut'; kw.update(word=text if isinstance(text, str) else text[0], size=s.get('size'), rot=s.get('rot', 0.0), d=d, fx=fx or 'beat', big=s.get('big', False), y=.5 - s.get('dy', 0) / 1080.0)
        elif st == 'slam':
            fn = 'slam'; kw.update(word=text if isinstance(text, str) else text[0], size=s.get('size'), d=d, fx=fx or 'hit', big=s.get('big', False))
        elif st == 'punch3d':
            fn = 'punch'; kw.update(word=text if isinstance(text, str) else text[0], f0=('beat', s['at'] - a), charge=bool(o.get('charge') and i == 0)); kw.pop('d', None)
        elif st == 'stack':
            fn = 'stack'; kw.update(kicker=text[0], word=text[1], d=d, fx=fx or 'none', second=s.get('second', .5))
        elif st == 'pair':
            fn = 'pair'; kw.update(a=text[0], b=text[1], d=d, fx=fx or 'beat', second=s.get('second', .5)); kw.pop('col', None)
        elif st == 'split':
            fn = 'split'; kw.update(small=text[0], big=text[1], d=d, fx=fx or 'punch', heavy=s.get('big', False), second=s.get('second', .5))
            if 'col' not in kw: kw['col'] = 'accent'
        else:
            fn = 'slam'; kw.update(word=str(text), d=d); notes.append('unknown word style "%s" became a slam' % st)
        if o.get('charge') and i == 0 and st != 'punch3d': notes.append('charge-up lines only draw before a punch3d first shot')
        for feat, label in (('scramble', 'glyph scramble'), ('glitch', 'RGB glitch'), ('rgb', 'RGB split'), ('flip', 'mid-shot colour flip'), ('note', 'typed note line'), ('code', 'code backdrop'), ('glyphs', 'glyph burst')):
            if s.get(feat): notes.append('"%s": %s not converted' % (_name(text), label))
        out.append(dict(name=_name(text), k0=a, k1=b, ground=s.get('ground', 'bg'), fn=fn, kw=kw))
    return out

def _strike(sc, film):
    k1, o = sc['k1'], sc['o']; items = o.get('items', []); out = []
    for i, it in enumerate(items):
        b = items[i + 1]['at'] if i + 1 < len(items) else k1
        kw = dict(word=_tok(it['word'], film), ui=it.get('ui'), no=o.get('no', 'NO'))
        if i: kw['whip_in'] = (X, 0)
        if i + 1 < len(items): kw['whip_out'] = (-X, 0)
        elif o.get('tvOff', True) is not False: kw['tv_off'] = True
        out.append(dict(name='%s %s' % (kw['no'], kw['word']), k0=it['at'], k1=b, ground=it.get('ground', 'bg'), fn='strike', kw=kw))
    return out

def _even(sc, labels):
    """Split a block evenly into len(labels) shots, as (a, b, label)."""
    k0, k1 = sc['k0'], sc['k1']; n = max(1, len(labels)); step = (k1 - k0) / float(n)
    return [(k0 + i * step, k0 + (i + 1) * step, l) for i, l in enumerate(labels)]

def _wrap(text, width=38):
    lines, cur = [], ''
    for w in text.split():
        if len(cur) + len(w) + 1 > width: lines.append(cur); cur = w
        else: cur = (cur + ' ' + w).strip()
    return '\n'.join(lines + [cur])

def plan_film(film):
    shots, notes = [], []
    for sc in film['scenes']:
        b, k0, k1, o = sc['block'], sc['k0'], sc['k1'], sc['o']
        g = o.get('ground', 'bg')
        if b == 'Words': new = _words(sc, film, notes)
        elif b == 'Strike': new = _strike(sc, film)
        elif b == 'Hero':
            new = [dict(name=_name(o.get('title', 'Hero')), k0=k0, k1=k1, ground=g, fn='hero', kw=dict(kicker=_tok(o.get('kicker'), film), title=_tok(o.get('title', ''), film), sub=_tok(o.get('sub'), film)))]
        elif b == 'Fly':
            new = [dict(name='Fly through', k0=k0, k1=k1, ground=g, fn='fly', kw=dict(words=[[_tok(w[0], film), w[1] if len(w) > 1 else 'paper'] for w in o.get('words', [])]))]
        elif b == 'Stretch':
            new = [dict(name=_name(o.get('word', 'ELASTIC.')), k0=k0, k1=k1, ground=g, fn='stretch', kw=dict(word=_tok(o.get('word', 'ELASTIC.'), film), grounds=o.get('grounds')))]
            notes.append('%s: the stretch is a horizontal scale, not the variable width axis' % o.get('word', 'Stretch'))
        elif b == 'Picture':
            src = o.get('src', '')
            path = src if os.path.isabs(src) else film['film'] + '/' + src
            if not os.path.exists(path): notes.append('MISSING ART %s: the Picture shot will be empty until the file exists' % src)
            if o.get('weather'): notes.append('%s: %s weather layer not converted' % (src, o['weather']))
            new = [dict(name=os.path.basename(src) or 'Picture', k0=k0, k1=k1, ground=g, fn='picture', kw=dict(src=path, words=o.get('words', []), cutIns=o.get('cutIns', []), tint=o.get('tint', .25), focus=o.get('focus', [.5, .5]), x=o.get('x'), y=o.get('y')))]
        elif b == 'Logo':
            new = [dict(name='Logo', k0=k0, k1=k1, ground=g, fn='logo', kw=dict(tagline=_tok(o.get('tagline'), film), small=_tok(o.get('small'), film), wordmark=o.get('wordmark') or film.get('title'), assets=film.get('logoAssets'), width=o.get('width', 840)))]
        elif b == 'Graph':
            new = [dict(name='%s %s' % (o.get('number', ''), o.get('label', '')), k0=k0, k1=k1, ground=o.get('ground', 'paper'), fn='stack', kw=dict(kicker=_tok(o.get('label', ''), film), word=_tok(str(o.get('number', '')), film), second=1.0))]
            notes.append('Graph "%s": the drawn curve and portal became a kicker and big number' % o.get('label', ''))
        elif b == 'Counters':
            new = [dict(name='%s %s' % (l[0], l[1]), k0=a, k1=z, ground=g, fn='stack', kw=dict(kicker=_tok(l[1], film), word=_tok(l[0], film))) for a, z, l in _even(sc, o.get('counters', []))]
            notes.append('Counters: slot reels and the source-code plane became a kicker and big number per counter')
        elif b == 'Progress':
            ln = o.get('lines', ['', ''])
            new = [dict(name=_name(ln), k0=k0, k1=k1, ground=o.get('ground', 'paper'), fn='stack', kw=dict(kicker=_tok(ln[0], film), word=_tok(ln[1] if len(ln) > 1 else ln[0], film)))]
            notes.append('Progress: the frame conveyor and progress bar became a kicker and word')
        elif b == 'Chain':
            new = [dict(name=_name(l[0]), k0=a, k1=z, ground=l[2] if len(l) > 2 else g, fn='stack', kw=dict(kicker=_tok(l[1], film) if len(l) > 1 else '', word=_tok(l[0], film))) for a, z, l in _even(sc, o.get('nodes', []))]
            notes.append('Chain: the comet ride and pull-back became one card per node')
        elif b == 'Prompt':
            text = ''.join(t[0] for t in o.get('text', [])) if isinstance(o.get('text'), list) else str(o.get('text', ''))
            new = [dict(name=o.get('label', 'Prompt'), k0=k0, k1=k1, ground=g, fn='typed', kw=dict(text=_wrap(_tok(text, film)), label=o.get('label'), start=1.3 / 19, end=11.4 / 19, flash_at=('beat', k1 - k0 - 2)))]
            notes.append('Prompt: typed with no keyword highlights or camera follow')
        elif b == 'Notes':
            new = [dict(name=_name(l[0]), k0=a, k1=z, ground=g, fn='typed', kw=dict(text=_wrap(_tok(l[0], film), 26), label=o.get('file'), size=.12, end=.6)) for a, z, l in _even(sc, o.get('notes', []))]
            notes.append('Notes: each note is typed on its own card; the preview and timeline reactions are not converted')
        elif b == 'Rewind':
            new = [dict(name='Rewind', k0=k0, k1=k1, ground=g, fn='cut', kw=dict(word=o.get('label', 'REWIND.')))]
            notes.append('Rewind: the reverse playback window is not converted. Reverse-speed a copy of the earlier clips on V1 if you want it')
        else:
            new = [dict(name=b, k0=k0, k1=k1, ground=g, fn='cut', kw=dict(word=b.upper()))]
            notes.append('Unknown block %s became a title card' % b)
        if new and o.get('whipOut'): new[-1]['kw']['whip_out'] = _whip(o['whipOut'], True)
        if new and o.get('whipIn'): new[0]['kw']['whip_in'] = _whip(o['whipIn'], False)
        if shots and o.get('whipIn') is None and shots[-1]['kw'].get('whip_out') and b != 'Strike' and 'whip_in' not in new[0]['kw']:
            w = shots[-1]['kw']['whip_out']; new[0]['kw']['whip_in'] = (-w[0], -w[1])   # land from the side the last shot left to
        shots += new
    if film.get('hud'): notes.append('HUD overlay not converted')
    if film.get('captions'): notes.append('Karaoke captions not converted: %d lines' % len(film['captions']))
    notes.append('Film grain and page-level bloom are not added')
    seen, unique = set(), []
    for n in notes:
        if n not in seen: seen.add(n); unique.append(n)
    return shots, unique

def all_words(shots):
    """Every word whose width matters, for measure_fonts.py."""
    out = set()
    def walk(v):
        if isinstance(v, str): out.add(v)
        elif isinstance(v, (list, tuple)):
            for x in v: walk(x)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in ('assets', 'ui', 'src', 'col', 'fn', 'fx', 'no') or k in ('no',): walk(x)
    for s in shots:
        walk(s['kw'])
        ui = s['kw'].get('ui') or {}
        for t in ui.get('tiles') or []: out.add(t[0])
    return sorted(w for w in out if w and len(w) < 200)
