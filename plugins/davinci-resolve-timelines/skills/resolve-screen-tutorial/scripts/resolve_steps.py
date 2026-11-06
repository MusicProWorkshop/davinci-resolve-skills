# Runs inside Resolve's scripting host, through run_script_unsafe. Each call starts with:
#     SKILL = r'<skill>'; WORK = r'<film>'
#     exec(open(SKILL + r'\scripts\resolve_steps.py', encoding='utf8').read())
# after which `project` and `resolve` are the ones the host supplies. SKILL.md has the order of the steps.
import contextlib
import importlib.util
import io
import json
import os
import time


def _build(work):
    return os.path.join(work, 'build')


def _film(work):
    with open(os.path.join(work, 'film.json'), encoding='utf8') as f:
        return json.load(f)


def _plan(work):
    with open(os.path.join(_build(work), 'plan.json'), encoding='utf8') as f:
        return json.load(f)


def _state(work):
    path = os.path.join(_build(work), 'state.json')
    if os.path.exists(path):
        with open(path, encoding='utf8') as f:
            return json.load(f)
    return {}


def _save_state(work, state):
    with open(os.path.join(_build(work), 'state.json'), 'w', encoding='utf8') as f:
        json.dump(state, f)


def timeline_named(project, name):
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t.GetName() == name:
            return t
    return None


def _delete_timeline(project, t):
    current = project.GetCurrentTimeline()
    if current and current.GetUniqueId() == t.GetUniqueId():
        for i in range(1, project.GetTimelineCount() + 1):
            other = project.GetTimelineByIndex(i)
            if other.GetUniqueId() != t.GetUniqueId():
                project.SetCurrentTimeline(other)
                break
    return project.GetMediaPool().DeleteTimelines([t])


def _film_bin(project, plan):
    mp = project.GetMediaPool()
    folder = mp.GetRootFolder()
    for name in [part for part in plan['bin'].split('/') if part] + [plan['name']]:
        folder = next((f for f in folder.GetSubFolderList() if f.GetName() == name), None) or mp.AddSubFolder(folder, name)
    return folder


def _scratch(plan, kind):
    return '__%s_%s' % (kind, plan['name'])


def project_format(project):
    """What to write film.json for. Read-only, and needs no film yet."""
    return dict(project=project.GetName(), width=project.GetSetting('timelineResolutionWidth'), height=project.GetSetting('timelineResolutionHeight'),
                fps=project.GetSetting('timelineFrameRate'), timelines=[project.GetTimelineByIndex(i).GetName() for i in range(1, project.GetTimelineCount() + 1)])


def fonts_available(*names):
    """Text+ only sees installed fonts: {name: its styles, or None if missing}."""
    fonts = resolve.Fusion().FontManager.GetFontList()
    return {n: sorted(fonts[n].keys()) if n in fonts else None for n in names}


def preflight(project, work):
    """Read-only. Says which project this lands in and what would stop the build."""
    film = _film(work)
    brand = film.get('brand', {})
    if isinstance(brand, str):
        with open(os.path.join(work, brand), encoding='utf8') as f:
            brand = json.load(f)
    fps = int(film.get('fps', 60))
    problems = []
    width, height = project.GetSetting('timelineResolutionWidth'), project.GetSetting('timelineResolutionHeight')
    rate = project.GetSetting('timelineFrameRate')
    if str(width) != '1920' or str(height) != '1080':
        problems.append('The project timeline is %sx%s and this build only works at 1920x1080.' % (width, height))
    notes = []
    if float(rate) != fps:
        notes.append('The project runs at %s fps and film.json asks for %d, so this timeline will have its own frame rate setting. Tell the user.' % (rate, fps))
    mismatch = project.GetSetting('timelineInputResMismatchBehavior')
    if mismatch not in (None, '', 'scaleToFit'):
        problems.append('Mismatched resolution files are set to "%s", and camera positions assume "Scale entire image to fit".' % mismatch)
    fonts = resolve.Fusion().FontManager.GetFontList()
    family = brand.get('font', 'Lato')
    styles = {'regular': 'Regular', 'bold': 'Bold', 'black': 'Black', **brand.get('styles', {})}
    needed = {family: {styles['regular'], styles['bold']}}
    if brand.get('wordmark'):
        word_family = brand.get('wordmarkFont') or family
        word_style = brand.get('wordmarkStyle') or styles['black']
        needed.setdefault(word_family, set()).add(word_style)
    for name, wanted in needed.items():
        if name not in fonts:
            problems.append('The font %s is not installed.' % name)
            continue
        absent = sorted(s for s in wanted if s not in fonts[name])
        if absent:
            problems.append('%s has no style %s. It has %s.' % (name, absent, sorted(fonts[name].keys())))
    taken = timeline_named(project, film['name'])
    state = _state(work) if os.path.isdir(_build(work)) else {}
    if taken and taken.GetUniqueId() != state.get('timeline_id'):
        problems.append('A timeline named "%s" already exists and was not built from this folder. Pick another name.' % film['name'])
    current = project.GetCurrentTimeline()
    return dict(project=project.GetName(), current_timeline=current.GetName() if current else None,
                timelines=[project.GetTimelineByIndex(i).GetName() for i in range(1, project.GetTimelineCount() + 1)],
                size=(width, height), fps=rate, problems=problems, notes=notes)


def make_blueprint(project, work):
    """Exports one of each title, as Resolve itself expands the templates, for patch_drt.py to clone."""
    plan = _plan(work)
    mp = project.GetMediaPool()
    mp.SetCurrentFolder(_film_bin(project, plan))
    name = _scratch(plan, 'blueprint')
    old = timeline_named(project, name)
    t = mp.CreateEmptyTimeline(name + '_new')
    project.SetCurrentTimeline(t)
    if old:
        _delete_timeline(project, old)
    t.SetName(name)
    made, missing, done = [], [], set()
    for attempt in range(5):
        missing = []
        for k, kind in enumerate(['Caption', 'Card', 'Highlight', 'Click']):
            title = '%s %s' % (plan['brand_prefix'], kind)
            if title in done:
                continue
            t.SetCurrentTimecode('01:%02d:00:00' % k)
            item = t.InsertFusionTitleIntoTimeline(title)
            if not item:
                missing.append(title)
                continue
            done.add(title)
            # A title's comp only exports with its data once it has been opened.
            made.append((title, len(item.GetFusionCompByIndex(1).GetToolList(False))))
        if not missing:
            break
        # Resolve 21.2 can take a few seconds to list templates installed while it runs.
        time.sleep(3)
    if missing:
        raise RuntimeError('Resolve could not insert %s. Run templates.py with --install. If it has run, Resolve may need a restart to see new templates: ask the user.' % missing)
    ok = t.Export(os.path.join(_build(work), 'blueprint.drt'), resolve.EXPORT_DRT, resolve.EXPORT_NONE)
    return dict(made=made, exported=ok)


def import_raw(project, work):
    """Brings the clips into the media pool, and exports them for patch_drt.py."""
    plan = _plan(work)
    mp = project.GetMediaPool()
    mp.SetCurrentFolder(_film_bin(project, plan))
    name = _scratch(plan, 'raw')
    old = timeline_named(project, name)
    if old:
        _delete_timeline(project, old)
    t = mp.ImportTimelineFromFile(os.path.join(_build(work), 'film.xml'), {'timelineName': name})
    if not t:
        raise RuntimeError('Resolve did not import film.xml')
    return dict(rate=t.GetSetting('timelineFrameRate'), clips=sum(len(t.GetItemListInTrack('video', k) or []) for k in range(1, t.GetTrackCount('video') + 1)),
                exported=t.Export(os.path.join(_build(work), 'raw.drt'), resolve.EXPORT_DRT, resolve.EXPORT_NONE))


def _used_tracks(plan):
    return [name for name in plan['tracks'] if any(i['track'] == name for i in plan['clips'] + plan['titles'])]


def import_final(project, work):
    """Imports final.drt as the film's timeline. A timeline of that name is only replaced if this folder built it, and its edits are lost."""
    plan = _plan(work)
    state = _state(work)
    old = timeline_named(project, plan['name'])
    if old and old.GetUniqueId() != state.get('timeline_id'):
        raise RuntimeError('A timeline named "%s" already exists and was not built from this folder. Change "name" in film.json and run plan.py again.' % plan['name'])
    mp = project.GetMediaPool()
    mp.SetCurrentFolder(_film_bin(project, plan))
    t = mp.ImportTimelineFromFile(os.path.join(_build(work), 'final.drt'))
    if not t:
        raise RuntimeError('Resolve did not import final.drt')
    if old:
        _delete_timeline(project, old)
    t.SetName(plan['name'])
    project.SetCurrentTimeline(t)
    used = _used_tracks(plan)
    for k, name in enumerate(used, 1):
        t.SetTrackName('video', k, name)
    _save_state(work, dict(timeline_id=t.GetUniqueId(), finished=0, failed_dissolves=[]))
    return dict(timeline=t.GetName(), tracks=used)


def _items_by_start(t):
    out = {}
    for k in range(1, t.GetTrackCount('video') + 1):
        name = t.GetTrackName('video', k)
        for item in t.GetItemListInTrack('video', k) or []:
            out[(name, item.GetStart())] = item
    return out


def _finish_title(by_start, base, spec):
    item = by_start[(spec['track'], base + spec['start'])]
    comp = item.GetFusionCompByIndex(1)
    for tool_name, inputs in spec['inputs'].items():
        tool = comp.FindTool(tool_name)
        for key, value in inputs.items():
            tool.SetInput(key, value)
    if any(spec.get('fades', [])):
        item.SetFades({'FadeIn': spec['fades'][0], 'FadeOut': spec['fades'][1]})


def _finish_clip(by_start, base, spec):
    item = by_start[(spec['track'], base + spec['start'])]
    still = {}
    for name, channel in spec['transform'].items():
        if not channel.get('keys'):
            if name == 'zoom':
                still.update(ZoomX=channel['static'], ZoomY=channel['static'])
            elif name == 'pan':
                still['Pan'] = channel['static'] * 1920
            else:
                still['Tilt'] = channel['static'] * 1080
    if spec.get('crop'):
        still.update(CroppingEnabled=True, **spec['crop'])
    if still and not item.SetProperties(still):
        raise RuntimeError('SetProperties failed at %d: %s' % (spec['start'], still))
    if any(spec.get('fades', [])):
        item.SetFades({'FadeIn': spec['fades'][0], 'FadeOut': spec['fades'][1]})


def finish_batch(project, work, seconds=45):
    """Title text and settings, values that don't animate, crops, fades, dissolves, then markers. Call until done is true: it resumes where it stopped."""
    plan = _plan(work)
    state = _state(work)
    t = next((x for x in (project.GetTimelineByIndex(i) for i in range(1, project.GetTimelineCount() + 1)) if x.GetUniqueId() == state.get('timeline_id')), None)
    if not t:
        raise RuntimeError('The built timeline is gone. Run import_final again.')
    project.SetCurrentTimeline(t)
    base = plan['base']
    tasks = [('title', s) for s in plan['titles']] + [('clip', s) for s in plan['clips']] + [('dissolve', c) for c in plan['cuts']] + [('markers', None)]
    by_start = _items_by_start(t)
    screens = None
    began = time.time()
    index = state.get('finished', 0)
    while index < len(tasks) and time.time() - began < seconds:
        kind, spec = tasks[index]
        if kind == 'title':
            _finish_title(by_start, base, spec)
        elif kind == 'clip':
            _finish_clip(by_start, base, spec)
        elif kind == 'dissolve':
            screens = screens or t.GetItemListInTrack('video', 1)
            item = next((i for i in screens if i.GetStart() == base + spec), None)
            made = item.AddTransition({'type': 'Cross Dissolve', 'category': 'simple', 'position': 'start', 'alignment': 'center', 'duration': plan['transition']}) if item else None
            if not made:
                state['failed_dissolves'].append(spec)
        else:
            t.DeleteMarkersByColor('Blue')
            for m in plan['markers']:
                t.AddMarker(m['frame'], 'Blue', m['name'], '', 1)
        index += 1
        state['finished'] = index
        _save_state(work, state)
    return dict(done=index >= len(tasks), finished=index, of=len(tasks), failed_dissolves=state['failed_dissolves'])


def verify(project, work):
    """Compares the timeline with the plan. problems should be empty."""
    plan = _plan(work)
    t = timeline_named(project, plan['name'])
    problems = []
    expected = {}
    for item in plan['clips'] + plan['titles']:
        expected[item['track']] = expected.get(item['track'], 0) + 1
    # Resolve lists each dissolve as an item on its track.
    expected['Screens'] = expected.get('Screens', 0) + len(plan['cuts']) - len(_state(work).get('failed_dissolves', []))
    actual, offline = {}, []
    files = {(c['track'], plan['base'] + c['start']): os.path.normcase(c['file']) for c in plan['clips']}
    for k in range(1, t.GetTrackCount('video') + 1):
        name = t.GetTrackName('video', k)
        items = t.GetItemListInTrack('video', k) or []
        actual[name] = len(items)
        for item in items:
            want = files.get((name, item.GetStart()))
            if want is None:
                continue
            pool = item.GetMediaPoolItem()
            path = pool.GetClipProperty('File Path') if pool else None
            if not path or os.path.normcase(path) != want:
                offline.append('%s at frame %d shows %s, expected %s' % (name, item.GetStart(), path, want))
    if actual != expected:
        problems.append('Track contents differ: expected %s, got %s' % (expected, actual))
    if offline:
        problems.append('Media: ' + '; '.join(offline[:5]))
    length = t.GetEndFrame() - t.GetStartFrame()
    if length != plan['total']:
        problems.append('Timeline is %d frames, the plan says %d' % (length, plan['total']))
    state = _state(work)
    if state.get('failed_dissolves'):
        problems.append('Dissolves failed at frames %s' % state['failed_dissolves'])
    if state.get('finished', 0) < len(plan['titles']) + len(plan['clips']) + len(plan['cuts']) + 1:
        problems.append('finish_batch has not finished')
    if int(float(t.GetSetting('timelineFrameRate'))) != plan['fps']:
        problems.append('Timeline runs at %s fps, the plan at %d' % (t.GetSetting('timelineFrameRate'), plan['fps']))
    return dict(tracks=actual, frames=length, seconds=length / plan['fps'], problems=problems)


def cleanup(project, work):
    """Deletes this build's scratch timelines and nothing else. Their clips stay, because the finished timeline uses them."""
    plan = _plan(work)
    removed = []
    for kind in ('blueprint', 'raw'):
        t = timeline_named(project, _scratch(plan, kind))
        if t and _delete_timeline(project, t):
            removed.append(_scratch(plan, kind))
    return dict(removed=removed)


def _patch(work):
    """Runs patch_drt.py here, because the python on PATH inside Resolve's host may lack its dependencies."""
    spec = importlib.util.spec_from_file_location('patch_drt', os.path.join(SKILL, 'scripts', 'patch_drt.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            module.main(work)
    except SystemExit as stop:
        raise RuntimeError('patch_drt.py: %s' % stop)
    return printed.getvalue().strip()


def build_film(project, work):
    """Everything from the blueprint to cleanup, in one call, after plan.py and templates.py. If done is false, repeat finish_batch, then call verify and cleanup."""
    began = time.time()
    blueprint = make_blueprint(project, work)
    raw = import_raw(project, work)
    patched = _patch(work)
    imported = import_final(project, work)
    finished = finish_batch(project, work, max(5, 45 - (time.time() - began)))
    out = dict(blueprint=blueprint['exported'], raw=raw['clips'], patched=patched, timeline=imported['timeline'], done=finished['done'], finished=finished)
    if finished['done']:
        out.update(verify=verify(project, work), cleanup=cleanup(project, work))
    return out


def _moments(plan):
    fps = plan['fps']
    rows = [(m['frame'] + int(fps * 0.75), '%s %.2fs' % (m['name'], m['frame'] / fps + 0.75)) for m in plan['markers']]
    for title in plan['titles']:
        kind = title['template'].rsplit(' ', 1)[-1]
        if kind == 'Highlight':
            f = (title['start'] + title['end']) // 2
            rows.append((f, 'highlight %.2fs' % (f / fps)))
        elif kind == 'Click':
            f = title['start'] + int(fps * 0.1)
            rows.append((f, 'click %.2fs' % (f / fps)))
    return sorted(set(rows))


def review_frames(project, work, seconds=None, per_sheet=12):
    """Frames straight from the timeline, with no render: labelled sheets of each scene, highlight and click, or the given times at full size."""
    plan = _plan(work)
    t = timeline_named(project, plan['name'])
    if not hasattr(t, 'ExportThumbnails'):
        raise RuntimeError('This Resolve has no Timeline.ExportThumbnails, which arrived by 21.2. Review from a render instead.')
    # A timeline that hasn't been opened exports black frames while still reporting success.
    project.SetCurrentTimeline(t)
    out = os.path.join(_build(work), 'review')
    os.makedirs(out, exist_ok=True)
    last = plan['total'] - 1
    files, failed = [], []
    if seconds:
        for s in seconds:
            path = os.path.join(out, 'at-%.2f.png' % s)
            r = t.ExportFrame(min(last, max(0, int(round(s * plan['fps'])))), {'outputType': 'file', 'filePath': path})
            (files if r.get('success') else failed).append(path if r.get('success') else '%s: %s' % (s, r.get('error')))
        return dict(files=files, failed=failed)
    rows = _moments(plan)
    for n, i in enumerate(range(0, len(rows), per_sheet)):
        chunk = [{'frameOffset': min(last, f), 'label': label} for f, label in rows[i:i + per_sheet]]
        path = os.path.join(out, 'frames-%02d.jpg' % n)
        r = t.ExportThumbnails(chunk, {'outputType': 'file', 'filePath': path, 'maxDimension': 2400, 'quality': 85})
        (files if r.get('success') else failed).append(path if r.get('success') else '%s: %s' % (path, r.get('error')))
    return dict(files=files, failed=failed, frames=len(rows))


def start_render(project, work, label='review'):
    """Queues and starts a render of the film. This changes the project's render settings, so say so."""
    plan = _plan(work)
    target = os.path.join(_build(work), 'render')
    os.makedirs(target, exist_ok=True)
    t = timeline_named(project, plan['name'])
    project.SetCurrentTimeline(t)
    previous = project.GetCurrentRenderFormatAndCodec()
    codecs = project.GetRenderCodecs('mp4')
    pick = next((v for k, v in codecs.items() if 'H.264' in k and any(g in k for g in ('NVIDIA', 'AMD', 'Intel', 'Apple', 'VideoToolbox'))), 'H264')
    project.SetCurrentRenderFormatAndCodec('mp4', pick)
    project.SetRenderSettings({'TargetDir': target, 'CustomName': label, 'SelectAllFrames': True, 'ExportVideo': True, 'ExportAudio': False,
                               'FormatWidth': 1920, 'FormatHeight': 1080, 'FrameRate': plan['fps']})
    job = project.AddRenderJob()
    if not job:
        return dict(job=None, why='The render queue is busy. Wait and call this again.')
    project.StartRendering([job], isInteractiveMode=False)
    return dict(job=job, codec=pick, previous_format=previous, file=os.path.join(target, label + '.mp4'))


def wait_render(project, job, seconds=50):
    began = time.time()
    while time.time() - began < seconds and project.IsRenderingInProgress():
        time.sleep(2)
    return project.GetRenderJobStatus(job)


def remove_job(project, job):
    """Removes only this job. The queue may hold the user's own."""
    return project.DeleteRenderJob(job)
