// export_film.mjs <film folder>: reads a kinetic film's spec.js in a real browser and writes <film>/resolve/film.json,
// with every scene as plain data, plus transparent PNGs of the logo. Needs Playwright in the film folder.
import fs from 'fs';
import path from 'path';
import http from 'http';
import { createRequire } from 'module';

const film = path.resolve(process.argv[2] || '.');
const out = path.join(film, 'resolve'), assets = path.join(out, 'assets');
fs.mkdirSync(assets, { recursive: true });
let chromium;
try { ({ chromium } = createRequire(film + path.sep)('playwright')); }
catch { console.error('Playwright not found. In the film folder run: npm install playwright'); process.exit(2); }

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.ttf': 'font/ttf', '.mp3': 'audio/mpeg', '.wav': 'audio/wav' };
const srv = http.createServer((q, r) => {
  const p = path.join(film, decodeURIComponent(q.url.split('?')[0]));
  fs.readFile(p, (e, d) => {
    r.setHeader('Access-Control-Allow-Origin', '*');
    if (e) { r.statusCode = 404; return r.end(); }
    r.setHeader('Content-Type', TYPES[path.extname(p)] || 'application/octet-stream'); r.end(d);
  });
});
await new Promise(ok => srv.listen(0, '127.0.0.1', ok));
const base = `http://127.0.0.1:${srv.address().port}/`;
const b = await chromium.launch({ channel: 'chrome' }).catch(() => chromium.launch());
const pg = await b.newPage({ viewport: { width: 1920, height: 1300 } });
await pg.goto(base + 'index.html?render=1');
await pg.waitForFunction(() => window.__ready, null, { timeout: 120000 }).catch(() => console.error('film page never reported ready; reading the spec anyway'));

const data = await pg.evaluate(async () => {
  const KNOWN = new Set(['Words', 'Strike', 'Graph', 'Hero', 'Prompt', 'Stretch', 'Fly', 'Notes', 'Counters', 'Progress', 'Chain', 'Rewind', 'Picture', 'Logo']);
  const spec = (await import('/spec.js')).default, f = window.__film || {};
  // a film may wrap a block in its own subclass, so walk up to the block it came from
  const blockName = cls => { for (let c = cls; c && c !== Function.prototype; c = Object.getPrototypeOf(c)) if (KNOWN.has(c.name)) return c.name; return cls.name || 'Unknown'; };
  const plain = o => JSON.parse(JSON.stringify(o, (k, v) => (typeof v === 'function' ? undefined : v)));
  return {
    title: spec.title || 'Film', bpm: spec.bpm, beats: spec.beats, fps: spec.fps || 60, palette: spec.palette, logo: spec.logo || null,
    hud: spec.hud || null, hudOut: spec.hudOut || null, music: spec.music || null, captions: plain(spec.captions || []), cues: plain(f.cues || []), lines: f.lines || 0, dur: f.dur || spec.beats * 60 / spec.bpm,
    scenes: spec.scenes.map(([cls, k0, k1, o]) => ({ block: blockName(cls), k0, k1, o: plain(o || {}) })),
  };
});

// the engine's effects layer: every comet, spark burst, slash, ray, ring, drifting light, starburst, dot flash, flash and
// invert the film draws, with its timing, position and colour. Comet paths are functions, so they are sampled per frame.
data.fx = await pg.evaluate(async () => {
  const { Film } = await import('/compositor.js');
  const core = await import('/core.js');
  const spec = (await import('/spec.js')).default, fps = spec.fps || 60;
  const box = document.createElement('div'); box.style.cssText = 'position:absolute;left:-99999px;width:1920px;height:1080px'; document.body.appendChild(box);
  const f = new Film(box, { src: { code: '', lines: 0 }, logo: '', spec, dsf: 1 });
  const plain = o => JSON.parse(JSON.stringify(o, (k, v) => (typeof v === 'function' ? undefined : v)));
  const r1 = v => Math.round(v * 10) / 10;
  const comets = f.comets.map(c => {
    const e = c.ease || core.E.inOutCubic, P = s => c.path(e(Math.min(1, Math.max(0, (s - c.t0) / Math.max(1e-6, c.t1 - c.t0)))), s);
    const pts = [], us = [];
    for (let s = c.t0; s <= c.t1 + 1e-9; s += 1 / fps) { pts.push(P(s).map(r1)); us.push(Math.round(e(Math.min(1, (s - c.t0) / Math.max(1e-6, c.t1 - c.t0))) * 1e5) / 1e5); }
    pts.push(P(c.t1).map(r1)); us.push(1);
    // the path itself, sampled evenly in its own parameter: an eased comet crosses its fast end in a few frames,
    // so per-frame samples alone would draw that end as straight segments
    const path = [];
    for (let i = 0; i <= 240; i++) path.push(c.path(i / 240, c.t0 + (c.t1 - c.t0) * i / 240).map(r1));
    return { ...plain(c), pts, us, path };
  });
  const out = { comets, tint: core.C.tint, tint2: core.C.tint2, grid: f.scenes.map(s => ({ t0: s.t0, t1: s.t1, noGrid: !!s.noGrid })) };
  for (const k of ['bursts', 'slashes', 'rays', 'rings', 'bokehs', 'stars', 'dots', 'flashes', 'inverts', 'shakes', 'bumps', 'whips', 'lights']) out[k] = plain(f[k]);
  box.remove();
  return out;
});

// the logo, as transparent PNGs that share one canvas, so the pieces line up when the comp stacks them
data.logoAssets = null;
const logoScene = data.scenes.find(s => s.block === 'Logo');
if (data.logo && logoScene && fs.existsSync(path.join(film, data.logo))) {
  const svg = fs.readFileSync(path.join(film, data.logo), 'utf8').replace(/<\?xml[^>]*\?>/, '').replace(/<metadata[\s\S]*?<\/metadata>/, '');
  const faces = fs.existsSync(path.join(film, 'fonts')) ? fs.readdirSync(path.join(film, 'fonts')).filter(n => n.endsWith('.ttf')).map(n => `@font-face{font-family:'${n.slice(0, -4)}';src:url('${base}fonts/${n}');font-weight:100 900;font-stretch:62% 125%}`).join('') : '';
  const width = (logoScene.o.width || 840) * 2;
  const lp = await b.newPage({ viewport: { width: Math.max(2200, width + 40), height: 1400 } });
  await lp.setContent(`<!doctype html><style>${faces}html,body{margin:0;background:transparent}svg{display:block;overflow:visible}</style><div id="h"></div><style id="v"></style>`);
  const box = await lp.evaluate(async ([svg, width]) => {
    h.innerHTML = svg; const s = h.querySelector('svg');
    const vb = (s.getAttribute('viewBox') || `0 0 ${s.getAttribute('width')} ${s.getAttribute('height')}`).split(/[\s,]+/).map(Number);
    s.setAttribute('width', width); s.setAttribute('height', Math.round(width * vb[3] / vb[2]));
    await document.fonts.ready; await Promise.all([...document.fonts].map(f => f.load().catch(() => 0)));
    return { width, height: Math.round(width * vb[3] / vb[2]) };
  }, [svg, width]);
  const shot = async (name, ids) => {
    const css = ids ? `svg *{visibility:hidden}${ids.map(i => `#${CSS_ESC(i)},#${CSS_ESC(i)} *{visibility:visible}`).join('')}` : '';
    await lp.evaluate(c => { document.getElementById('v').textContent = c; }, css);
    const file = path.join(assets, name + '.png');
    await lp.screenshot({ path: file, omitBackground: true, clip: { x: 0, y: 0, width: box.width, height: box.height } });
    return file.replace(/\\/g, '/');
  };
  const CSS_ESC = s => s.replace(/([^\w-])/g, '\\$1');
  const a = { width: box.width, height: box.height, all: await shot('logo_all'), marks: [], word: null };
  for (const id of logoScene.o.mark || []) a.marks.push(await shot('logo_mark_' + id, [id]));
  if ((logoScene.o.word || []).length) a.word = await shot('logo_word', logoScene.o.word);
  data.logoAssets = a;
  await lp.close();
}
// images the Resolve build places in 3D: the Fly block's chamfered portal frame, and a sheet of dust for the tunnel
// (both drawn as the engine draws them, in the film's colours), and the engine's glyph set for glyph bursts
const ap = await b.newPage({ viewport: { width: 400, height: 300 } });
const imgs = await ap.evaluate(([acc, paper]) => {
  const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const rgba = (h, a) => `rgba(${hex(h).join(',')},${a})`;
  const cham = (x, y, w, h, c) => [[x + c, y], [x + w - c, y], [x + w, y + c], [x + w, y + h - c], [x + w - c, y + h], [x + c, y + h], [x, y + h - c], [x, y + c], [x + c, y]];
  const poly = (g, pts, col, lw) => { g.strokeStyle = col; g.lineWidth = lw; g.lineJoin = 'round'; g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.stroke(); };
  const portal = document.createElement('canvas'); portal.width = 1560; portal.height = 760;
  const p = portal.getContext('2d');
  poly(p, cham(6, 6, 1548, 748, 40), rgba(acc, .25), 12); poly(p, cham(6, 6, 1548, 748, 40), acc, 3.5); poly(p, cham(330, 220, 900, 320, 24), rgba(paper, .18), 2);
  const dust = document.createElement('canvas'); dust.width = 3000; dust.height = 2000;
  const d = dust.getContext('2d');
  let s = 77; const r = () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
  for (let i = 0; i < 260; i++) {
    const a = r() * Math.PI * 2, rad = 380 + r() * 1300, sz = .6 + r(), x = 1500 + Math.cos(a) * rad * .9, y = 1000 + Math.sin(a) * rad * .63;
    d.fillStyle = rgba(sz > 1.3 ? acc : paper, .75); d.beginPath(); d.arc(x, y, 1.6 * sz, 0, 7); d.fill();
  }
  return { portal: portal.toDataURL('image/png'), dust: dust.toDataURL('image/png') };
}, [(data.palette || {}).accent || '#FF5B2E', (data.palette || {}).paper || '#F4F1EA']);
data.flyAssets = {};
for (const [k, v] of Object.entries(imgs)) {
  const file = path.join(assets, 'fly_' + k + '.png');
  fs.writeFileSync(file, Buffer.from(v.split(',')[1], 'base64'));
  data.flyAssets[k] = file.replace(/\\/g, '/');
}
await ap.close();

data.film = film.replace(/\\/g, '/');
fs.writeFileSync(path.join(out, 'film.json'), JSON.stringify(data, null, 1));
const count = {}; data.scenes.forEach(s => { count[s.block] = (count[s.block] || 0) + 1; });
console.log(JSON.stringify({ title: data.title, bpm: data.bpm, beats: data.beats, seconds: +data.dur.toFixed(2), blocks: count, logo: !!data.logoAssets, music: data.music && data.music.file, wrote: path.join(out, 'film.json') }));
await Promise.race([b.close(), new Promise(r => setTimeout(r, 3000))]);
srv.close(); process.exit(0);
