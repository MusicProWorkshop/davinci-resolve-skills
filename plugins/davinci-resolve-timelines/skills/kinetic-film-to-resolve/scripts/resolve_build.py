# resolve_build.py: the steps that touch Resolve. Load inside run_script_unsafe with:
#   SKILL = r'<skill folder>'; exec(open(SKILL + r'\scripts\resolve_build.py', encoding='utf-8').read())
import json, os, re, subprocess, time
for _f in ('fusion_lib.py', 'plan.py'):
    exec(open(os.path.join(SKILL, 'scripts', _f), encoding='utf-8').read())

def _timeline(project, name):
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t.GetName() == name: return t
    return None

def _paths(film_dir): return os.path.join(film_dir, 'resolve')
def _cfg(film_dir): return json.load(open(os.path.join(_paths(film_dir), 'config.json'), encoding='utf-8'))
def _film(film_dir): return json.load(open(os.path.join(_paths(film_dir), 'film.json'), encoding='utf-8'))

def _configure(cfg, film):
    C.update(W=cfg['w'], H=cfg['h'], FPS=cfg['fps'], BPM=film['bpm'], FONT=cfg['font'], STYLE=cfg['style'], UI_FONT=cfg['ui_font'], UI_STYLE=cfg['ui_style'], PAL=film['palette'])
    C['ASSETS'] = os.path.join(_paths(cfg['film_dir']), 'assets')
    p = os.path.join(_paths(cfg['film_dir']), 'em.json')
    C['EM'] = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}

def fonts_available(resolve, *names):
    """Text+ only sees installed fonts: {name: its styles, or None if missing}."""
    lst = resolve.Fusion().FontManager.GetFontList()
    return {n: sorted(lst[n].keys()) if n in lst else None for n in names}

def setup(resolve, project, film_dir, timeline_name, font, style, ui_font, ui_style, replace=False):
    """Create the timeline, bin and placeholder clip, and write words.json for measure_fonts.py. Nothing else in the project changes."""
    film = _film(film_dir)
    missing = {k: v for k, v in fonts_available(resolve, font, ui_font).items() if v is None}
    if missing: raise RuntimeError('fonts not installed: %s. Ask the user which installed font to use.' % list(missing))
    pool = project.GetMediaPool()
    old = _timeline(project, timeline_name)
    if old and not replace: raise RuntimeError('timeline "%s" already exists. Use another name, or replace=True only for a timeline this skill built.' % timeline_name)
    if old:
        others = [project.GetTimelineByIndex(i) for i in range(1, project.GetTimelineCount() + 1)]
        others = [t for t in others if t.GetName() != timeline_name]
        if others: project.SetCurrentTimeline(others[0])
        pool.DeleteTimelines([old])
    tl = pool.CreateEmptyTimeline(timeline_name); project.SetCurrentTimeline(tl)
    w, h = int(tl.GetSetting('timelineResolutionWidth')), int(tl.GetSetting('timelineResolutionHeight'))
    fps = float(tl.GetSetting('timelineFrameRate'))
    cfg = dict(film_dir=film_dir, timeline=timeline_name, font=font, style=style, ui_font=ui_font, ui_style=ui_style, w=w, h=h, fps=fps, next=0)
    # the placeholder is the media under every comp: AddFusionComp needs a clip, and Fusion shots stay trimmable like any clip
    carrier = os.path.join(_paths(film_dir), 'carrier_black.mov').replace('\\', '/')
    secs = max(s['k1'] - s['k0'] for s in film['scenes']) * 60.0 / film['bpm'] + 2
    if not os.path.exists(carrier):
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=%dx%d:r=%g:d=%.2f' % (w, h, fps, secs), '-c:v', 'libx264', '-preset', 'ultrafast', '-qp', '30', '-pix_fmt', 'yuv420p', carrier], check=True)
    root = pool.GetRootFolder()
    parent = next((f for f in root.GetSubFolderList() if f.GetName() == 'Kinetic Films'), None) or pool.AddSubFolder(root, 'Kinetic Films')
    folder = next((f for f in parent.GetSubFolderList() if f.GetName() == film['title']), None) or pool.AddSubFolder(parent, film['title'])
    pool.SetCurrentFolder(folder)
    clips = [c for c in (folder.GetClipList() or []) if 'carrier' in c.GetName()]
    if not clips: clips = pool.ImportMedia([carrier])
    cfg['bin'] = ['Kinetic Films', film['title']]
    json.dump(cfg, open(os.path.join(_paths(film_dir), 'config.json'), 'w', encoding='utf-8'), indent=1)
    shots, notes = plan_film(film)
    json.dump(all_words(shots), open(os.path.join(_paths(film_dir), 'words.json'), 'w', encoding='utf-8'))
    return dict(timeline=timeline_name, size=(w, h), fps=fps, shots=len(shots), notes=notes, film_fps=film['fps'])

def _carrier(project, cfg):
    f = project.GetMediaPool().GetRootFolder()
    for n in cfg['bin']: f = next(x for x in f.GetSubFolderList() if x.GetName() == n)
    return next(c for c in f.GetClipList() if 'carrier' in c.GetName())

def _res(v):
    """('beat', n[, x]) in a plan means n beats, as frames; kept symbolic so the plan stays independent of the tempo."""
    if isinstance(v, (list, tuple)) and v and v[0] == 'beat':
        return beat(v[1]) if len(v) == 2 else (beat(v[1]), v[2])
    return v

def build_batch(project, film_dir, seconds=40):
    """Builds shots until the time budget runs out; a script call may only run 60 s. Call again until done is True."""
    cfg = _cfg(film_dir); film = _film(film_dir); _configure(cfg, film)
    shots, _ = plan_film(film)
    tl = _timeline(project, cfg['timeline']); project.SetCurrentTimeline(tl)
    pool = project.GetMediaPool(); carrier = _carrier(project, cfg); t0 = tl.GetStartFrame()
    start = time.time(); i = cfg['next']; errors = []
    while i < len(shots) and time.time() - start < seconds:
        sh = shots[i]
        f0, f1 = beat(sh['k0']), beat(sh['k1'])
        if f1 <= f0:
            i += 1; continue
        it = pool.AppendToTimeline([{'mediaPoolItem': carrier, 'startFrame': 0, 'endFrame': f1 - f0, 'mediaType': 1, 'trackIndex': 1, 'recordFrame': t0 + f0}])[0]
        # Resolve 21.2 refuses a clip name with any of \ / : * ? " < > |, so those are dropped when the full name is refused.
        it.SetName(sh['name']) or it.SetName(re.sub(r'[\\/:*?"<>|]', '', sh['name']).strip())
        comp = it.AddFusionComp()
        s = Shot(comp, f1 - f0, sh['ground'])
        kw = {k: _res(v) for k, v in sh['kw'].items() if v is not None}
        globals()[sh['fn']](s, **kw)
        s.finish()
        i += 1
    cfg['next'] = i
    json.dump(cfg, open(os.path.join(_paths(film_dir), 'config.json'), 'w', encoding='utf-8'), indent=1)
    return dict(built=i, total=len(shots), done=i >= len(shots), seconds=round(time.time() - start, 1))

def frame_grid(project, film_dir, seconds=None, per_sheet=12):
    """Frames straight from the timeline, with no render: labelled sheets of the middle of every shot, or the given times at full size."""
    cfg = _cfg(film_dir); tl = _timeline(project, cfg['timeline'])
    if not hasattr(tl, 'ExportThumbnails'):
        raise RuntimeError('This Resolve has no Timeline.ExportThumbnails, which arrived by 21.2. Review from a render instead.')
    # A timeline that hasn't been opened exports black frames while still reporting success.
    project.SetCurrentTimeline(tl)
    out = os.path.join(_paths(film_dir), 'review'); os.makedirs(out, exist_ok=True)
    t0, last = tl.GetStartFrame(), tl.GetEndFrame() - tl.GetStartFrame() - 1
    files, failed = [], []
    if seconds:
        for s in seconds:
            path = os.path.join(out, 'at-%.2f.png' % s)
            r = tl.ExportFrame(min(last, max(0, int(round(s * cfg['fps'])))), {'outputType': 'file', 'filePath': path})
            (files if r.get('success') else failed).append(path if r.get('success') else '%s: %s' % (s, r.get('error')))
        return dict(files=files, failed=failed)
    rows = [(it.GetStart() - t0 + it.GetDuration() // 2, it.GetName()) for it in tl.GetItemListInTrack('video', 1) or []]
    for n, i in enumerate(range(0, len(rows), per_sheet)):
        chunk = [{'frameOffset': min(last, f), 'label': '%s %.2fs' % (name, f / cfg['fps'])} for f, name in rows[i:i + per_sheet]]
        path = os.path.join(out, 'frames-%02d.jpg' % n)
        r = tl.ExportThumbnails(chunk, {'outputType': 'file', 'filePath': path, 'maxDimension': 2400, 'quality': 85})
        (files if r.get('success') else failed).append(path if r.get('success') else '%s: %s' % (path, r.get('error')))
    return dict(files=files, failed=failed, shots=len(rows))

def add_markers(project, film_dir):
    """A marker on every scene, so an editor can see the film's structure on the ruler."""
    cfg = _cfg(film_dir); film = _film(film_dir); _configure(cfg, film)
    tl = _timeline(project, cfg['timeline'])
    n = 0
    for sc in film['scenes']:
        if tl.AddMarker(beat(sc['k0']), 'Blue', sc['block'], 'beat %g' % sc['k0'], 1): n += 1
    return n

def audio_from_timeline(project, film_dir, source_timeline):
    """Copy an existing music edit, cuts included, so both versions share one mix."""
    cfg = _cfg(film_dir); src = _timeline(project, source_timeline); tl = _timeline(project, cfg['timeline'])
    project.SetCurrentTimeline(tl)
    pool = project.GetMediaPool(); t0, s0 = tl.GetStartFrame(), src.GetStartFrame(); out = []
    for it in src.GetItemListInTrack('audio', 1):
        r = pool.AppendToTimeline([{'mediaPoolItem': it.GetMediaPoolItem(), 'startFrame': it.GetSourceStartFrame(), 'endFrame': it.GetSourceEndFrame(), 'mediaType': 2, 'trackIndex': 1, 'recordFrame': t0 + it.GetStart() - s0}])
        out.append((r[0].GetStart() - t0, r[0].GetDuration()))
    return out

def audio_from_file(project, film_dir, path, offset=0.0, stop_beat=None):
    """Place an audio file so `offset` seconds into it lands on beat 0; optionally end on stop_beat."""
    cfg = _cfg(film_dir); film = _film(film_dir); _configure(cfg, film)
    tl = _timeline(project, cfg['timeline']); project.SetCurrentTimeline(tl)
    pool = project.GetMediaPool(); clip = pool.ImportMedia([path])[0]
    start = int(round(offset * C['FPS'])); length = beat(stop_beat if stop_beat else film['beats'])
    r = pool.AppendToTimeline([{'mediaPoolItem': clip, 'startFrame': start, 'endFrame': start + length, 'mediaType': 2, 'trackIndex': 1, 'recordFrame': tl.GetStartFrame()}])
    return [(x.GetStart() - tl.GetStartFrame(), x.GetDuration()) for x in r]

def start_render(project, film_dir, name):
    """Queue and start a render of this timeline. Prefers a GPU H.264 encoder. Returns the job id."""
    cfg = _cfg(film_dir); tl = _timeline(project, cfg['timeline']); project.SetCurrentTimeline(tl)
    codecs = project.GetRenderCodecs('mp4')
    pick = next((v for k, v in codecs.items() if 'H.264' in k and any(g in k for g in ('NVIDIA', 'AMD', 'Intel', 'Apple', 'VideoToolbox'))), 'H264')
    project.SetCurrentRenderFormatAndCodec('mp4', pick)
    out = os.path.join(_paths(film_dir), 'out'); os.makedirs(out, exist_ok=True)
    project.SetRenderSettings({'TargetDir': out, 'CustomName': name, 'SelectAllFrames': True, 'ExportVideo': True, 'ExportAudio': tl.GetTrackCount('audio') > 0 and bool(tl.GetItemListInTrack('audio', 1)), 'FormatWidth': cfg['w'], 'FormatHeight': cfg['h'], 'FrameRate': cfg['fps']})
    job = project.AddRenderJob()     # returns None while a stopped render is still winding down: wait and call again
    if not job: return dict(job=None, why='render queue busy')
    project.StartRendering([job], False)
    return dict(job=job, codec=pick, file=os.path.join(out, name + '.mp4'))

def wait_render(project, job, seconds=50):
    t = time.time()
    while time.time() - t < seconds and project.IsRenderingInProgress(): time.sleep(2)
    return project.GetRenderJobStatus(job)

def remove_job(project, job):
    """Remove only this skill's job from the queue; the user's own jobs stay."""
    return project.DeleteRenderJob(job)
