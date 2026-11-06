---
name: kinetic-film-to-resolve
description: Convert a kinetic typography film made with the scenario-kinetic-film skill (a film folder with spec.js) into an editable DaVinci Resolve timeline, one real Fusion comp per shot, on the same beat grid. Use this whenever someone wants a kinetic film, launch film, teaser or motion graphics promo built, rebuilt, recreated or edited in DaVinci Resolve or Fusion, wants to tweak a code-made film on a timeline, or asks to use the Resolve integration to make a version of a film, even if they never say "convert" or "spec.js". Needs DaVinci Resolve Studio with its MCP scripting tools.
---

# Kinetic film to DaVinci Resolve

Turns a kinetic film's `spec.js` into a Resolve timeline where every shot is one clip with its own Fusion comp: real Text+ and Text3D, keyframed cameras, the same beat timing. An editor can then open any shot on the Fusion page, retype a word, trim it, or swap the music.

It is a rebuild in Resolve's tools, not a pixel match. Say what changed from the original (`setup` returns the list as `notes`), and report it to the user.

## Before you start

- Resolve Studio is running with a project open. Check with `get_resolve_status`, and call `get_whats_new` once, as the Resolve server asks.
- The film folder has `spec.js` and the engine files, with `npm install playwright` done in it.
- Python with Pillow outside Resolve, for measuring type. ffmpeg on PATH.

## Ask the user

Decide these before building, from the conversation if you can:

1. **Which project.** The timeline is added to the open project. Tell the user which one that is. Switching projects could drop their unsaved work, so ask them to switch if it is the wrong one.
2. **Timeline name.** Default `<title> (Fusion)`. Look at the existing timelines and pick a name that is free. Never reuse or replace one you did not build in this session.
3. **Font.** Text+ only sees installed fonts, and the film's Archivo usually is not one. Use the brand font if the project shows one. Call `fonts_available(resolve, 'Lato', 'Inter')` to check; do not install fonts without asking. Heavy weights read best: Black, Heavy, ExtraBold.
4. **Audio.** An existing timeline's music edit (`audio_from_timeline`), a file (`audio_from_file`), or none. If a timeline already holds this film with music on it, offer that first, because it keeps the user's edit.

## Steps

`SKILL` below is this skill's folder and `F` is the film folder. Each Resolve step goes through `run_script_unsafe`, which is limited to 60 s per call, and starts with:

```python
SKILL = r'<this skill folder>'; F = r'<film folder>'
exec(open(SKILL + r'\scripts\resolve_build.py', encoding='utf-8').read())
```

**1. Export the spec** (from a shell):

```bash
node "<SKILL>/scripts/export_film.mjs" "<F>"
```

Writes `<F>/resolve/film.json` and the logo as transparent PNGs, and prints the blocks it found.

**2. Create the timeline:**

```python
result = setup(resolve, project, F, 'My Film (Fusion)', 'Lato', 'Black', 'Inter', 'Medium')
```

The last two fonts are for small lines and mock UI. It makes the timeline, a `Kinetic Films / <title>` bin and a black placeholder clip, and returns the shot count and `notes`. Timeline size and frame rate come from the project, so a film made at 60 fps can land on a 30 fps timeline. It is only proven at 1920x1080, 60 fps, so look closely at other formats.

**3. Measure the type** (from a shell, using a Python that has Pillow):

```bash
python "<SKILL>/scripts/measure_fonts.py" "<F>" Lato Black
```

Without it, words use estimated widths and may not fill the frame well. If it reports no font file, carry on and check framing closely.

**4. Build.** Repeat until `done` is true; it resumes where it stopped:

```python
result = build_batch(project, F, 40)
```

Then add the HUD (only if the film has one), the audio and scene markers:

```python
result = dict(hud=add_hud(project, F), audio=audio_from_timeline(project, F, 'Music Edit'), markers=add_markers(project, F))
```

The HUD is one Fusion clip on track 2 over the whole film. An editor can disable that clip to drop it.

**5. Look at frames.** On Resolve 21.2 or later, this exports labelled sheets of the middle of every shot straight from the timeline in a few seconds, with no render and no change to render settings. They go to `<F>/resolve/review/`. Check that nothing is black, words stay in frame, kickers clear their words, and images cover the frame. Fix what's wrong before rendering. `frame_grid(project, F, seconds=[4.2, 9.35])` gives chosen moments at full size, such as the end of a whip.

```python
result = frame_grid(project, F)
```

The frames match a render of the same frame, checked on 21.2. On an older Resolve without `ExportThumbnails`, it raises an error, so judge from the render instead.

**6. Render, and measure motion.**

```python
result = start_render(project, F, 'my_film')    # picks a GPU H.264 encoder when there is one
# in later calls: result = wait_render(project, result_job_id, 50)
```

Expect about 2 to 4 minutes for 30 s at 1080p60 on a strong GPU. Afterwards remove only your own job with `remove_job`. The queue may hold the user's jobs. `start_render` changes the project's render settings, so say so.

Motion can only be measured from the video. Run `holds.py` and `dyn.py` from scenario-kinetic-film's scripts on the render, if they're installed. The targets are 40 % still frames or less, no hold over 0.6 s before the end card, and median motion of 2.5 or more. Report the numbers, including misses.

To change something, fix it and rebuild with `setup(..., replace=True)`, only on a timeline this skill built, then repeat steps 4 to 6. If the film's words changed, rerun step 3.

**7. Finish.** Leave saving to the user unless they ask: saving also commits any other unsaved edits they have open. Report the timeline name, the notes, the render time and the review numbers. Mention the placeholder clip must stay in its bin, or the shots may show as offline.

## What you must not do, and why

These each cost real time to find. The detail is in [references/fusion-traps.md](references/fusion-traps.md); read it before changing `fusion_lib.py` or if something goes wrong.

- **Do not lock a comp while building it.** The clip then renders black. Lock only around Loader creation, as `Shot.loader` does; otherwise setting the Loader's clip opens a modal file picker on the user's screen that stops all scripting.
- **Do not use `ExportCurrentFrameAsStill` to review.** It outruns Fusion and returns black or stale frames. `frame_grid`, which uses `Timeline.ExportFrame` and `ExportThumbnails`, is reliable, but only on the current timeline: a timeline that hasn't been opened exports black frames while still reporting success.
- **Do not stack motion blur.** Blur on a word's own move and on the camera multiplies the work. Only the camera blurs, and only during fast moves.
- **Do not assume a faster encoder fixes a slow render.** Fusion frame generation is usually the limit. Measure before changing settings.

## Reference

- [references/block-map.md](references/block-map.md): how each of the 14 blocks converts and what is approximated. Read it if a film uses Graph, Counters, Progress, Chain, Prompt, Notes or Rewind, or the user asks how close a shot will be.
- [references/fusion-traps.md](references/fusion-traps.md): API behaviour found the hard way, and how to recover a stuck Resolve.
