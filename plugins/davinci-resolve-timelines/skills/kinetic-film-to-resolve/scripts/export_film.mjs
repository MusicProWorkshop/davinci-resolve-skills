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
data.film = film.replace(/\\/g, '/');
fs.writeFileSync(path.join(out, 'film.json'), JSON.stringify(data, null, 1));
const count = {}; data.scenes.forEach(s => { count[s.block] = (count[s.block] || 0) + 1; });
console.log(JSON.stringify({ title: data.title, bpm: data.bpm, beats: data.beats, seconds: +data.dur.toFixed(2), blocks: count, logo: !!data.logoAssets, music: data.music && data.music.file, wrote: path.join(out, 'film.json') }));
await Promise.race([b.close(), new Promise(r => setTimeout(r, 3000))]);
srv.close(); process.exit(0);
