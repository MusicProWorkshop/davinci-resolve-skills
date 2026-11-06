---
name: resolve-screen-tutorial
description: Build a software tutorial, product walkthrough or screen demo as an editable DaVinci Resolve timeline from screenshots, with camera moves as real Inspector keyframes, a moving cursor, click ripples, element highlights, caption bars with role or step labels, and title and end cards as branded Fusion titles with Inspector controls. Use this whenever someone wants a how-to video, feature tour, onboarding clip or help-center video made in Resolve or from screenshots on a Resolve timeline, wants animated zooms and callouts on stills in Resolve, or wants reusable Fusion titles for captions and highlights, even if they never say "tutorial". For a video that already exists as Remotion code, use remotion-to-resolve, which builds on this. Needs DaVinci Resolve Studio with its MCP scripting tools.
---

# Screen tutorial on a Resolve timeline

Turns a description of a tutorial (`film.json`) and its screenshots into a timeline an editor can keep working on. Clips have ordinary Inspector keyframes, titles are Fusion titles with controls in the Inspector, and scenes are marked. It adds no audio, so narration and music go on afterwards.

The Resolve API can't set keyframes or a title's length, so the build writes them into a timeline file and imports it. `references/how-it-works.md` explains this and lists known problems. Read it if a step fails or Resolve is newer than 21.2.

## Before you start

- Resolve Studio is running with a project open. Check with `get_resolve_status`, and call `get_whats_new` once with `since` set to `21.0`, as the Resolve server asks.
- Outside Resolve: Python with `pillow`, and ffmpeg on PATH.
- The project's timeline format must be 1920x1080. `preflight` checks this.

## Decide with the user

Settle these from the conversation if you can, and ask only about what's missing:

1. **The project.** The timeline goes into the open project. Name it to the user. Switching projects could lose their unsaved work, so ask them to switch if it's the wrong one.
2. **The screenshots.** They come from the user, or you capture them. With Playwright, use a 1920x1080 viewport with `deviceScaleFactor: 2`: the images come out at 3840x2160, and `getBoundingClientRect` gives positions that are already right for `film.json`. Look at each supplied image, use the ones that fit the audience, and tell the user what you left out.
3. **The brand.** Colors, font, wordmark, and any labels such as Host or Admin. Look in the user's code or earlier titles first. Text+ only sees installed fonts, and don't install one without asking.
4. **The timeline's name.** Pick one that's free. Never replace a timeline you didn't build.

## Write the film

Make a folder for the film and write `film.json` in it. [references/film-format.md](references/film-format.md) has the format. Read it now.

Some timing that reads well:

- Show a scene for 6 to 10 s, and keep a caption up long enough to read twice, about 1 s per 8 characters.
- Move the camera over about 1 s, and let it settle before the cursor moves or the highlight shows.
- Move the cursor over about 0.8 s, and click about 0.3 s after it lands.
- Show the result of a click with a new shot right after it, if the new shot's layout lines up at the current zoom. If the page changes completely, end the scene just after the click and let the dissolve carry it to the next one.
- To keep the cursor still across a dissolve, start the next scene's cursor at the same place on the frame, using `x' = tx + x * zoom`.
- Use a card of about 3 s at each end.

Captions should say only what the screenshots show or the user told you, and anything you inferred goes in your report.

A highlight that misses its button is the most visible mistake this format can make, so measure instead of estimating. Images can display at a different scale than their real size, so don't read positions off them directly:

```bash
python "<SKILL>/scripts/measure.py" grid shot.png grid.png
```

Open `grid.png`, which has frame coordinates marked, to find a rough point on the button's fill. Then get its exact rectangle, and check the result:

```bash
python "<SKILL>/scripts/measure.py" at shot.png 1250 470
```

```bash
python "<SKILL>/scripts/measure.py" show shot.png check.png 1200,450,180,40
```

A button whose border matches a nearby colour can leak, so read the warnings, and lower the tolerance if the rectangle looks too big.

## Build

`SKILL` is this skill's folder and `WORK` is the film's folder. Shell steps run from anywhere. Resolve steps go through `run_script_unsafe`. Pass `timeout: 60` on every call, because the tool's default is 10 s and the steps can take longer. Each starts with:

```python
SKILL = r'<this skill folder>'; WORK = r'<film folder>'
exec(open(SKILL + r'\scripts\resolve_steps.py', encoding='utf8').read())
```

Before `film.json` exists, `project_format(project)` gives the project's size, frame rate and timelines, and `fonts_available('Lato', ...)` the installed fonts and their styles. Set `fps` to the project's rate unless there's a reason not to.

**1. Check the project.** Fix anything in `problems` before going on, asking the user where it's their call, and pass on any `notes`. It changes nothing.

```python
result = preflight(project, WORK)
```

**2. Plan, and install the titles.** Read the warnings and fix what matters in `film.json`. This puts the titles in Resolve's Templates folder for the brand, replacing any with the same names, so tell the user.

```bash
python "<SKILL>/scripts/plan.py" "<WORK>"
```

```bash
python "<SKILL>/scripts/templates.py" "<WORK>" --install
```

**3. Build the timeline.** This exports the building blocks, writes the timeline file, imports it, applies the settings the API can set, checks the result and removes this build's two scratch timelines. It only replaces a timeline this folder built, and edits made on it are lost, so ask first if the user may have edited it.

```python
result = build_film(project, WORK)
```

`verify.problems` should be empty. If `done` is false, repeat `result = finish_batch(project, WORK)` until it's true, then run `result = dict(verify=verify(project, WORK), cleanup=cleanup(project, WORK))`. Resolve can take a few seconds to see newly installed titles, so `build_film` waits for them. If it still can't insert them, ask the user to restart Resolve after saving their work.

Don't delete bins, here or when tidying up: clips can be linked from one bin to timelines elsewhere (see `references/how-it-works.md`).

**4. Look at it.** This exports labelled sheets of frames straight from the timeline: each scene, the middle of each highlight, and just after each click. It takes a few seconds and needs no render, so render settings don't change. Open the sheets in `build/review/`.

```python
result = review_frames(project, WORK)
```

Check that highlights sit on their elements, the cursor lands where it should, ripples are visible, captions fit, and nothing is black. For a closer look, `review_frames(project, WORK, seconds=[10.5, 20.2])` gives those moments at full size, in timeline seconds. `plan.py` prints when each scene starts, to convert from scene times.

The frames match a render of the same frame, as tested on Resolve 21.2. `review_frames` needs the frame export API that 21.2 has. On an older Resolve it raises an error, and the render below does the job: run `review.py` on it without a reference to get the same sheets.

**5. Render, when you need a file.** Render to give the user a video, or for `remotion-to-resolve`'s comparison. `start_render` changes the project's render settings, so say so.

```python
result = start_render(project, WORK, 'review')
```

```python
result = wait_render(project, '<job id>', 50)   # repeat until the status is Complete
```

```bash
python "<SKILL>/scripts/review.py" "<WORK>" "<WORK>/build/render/review.mp4"
```

Remove your job, and only yours, since the queue may hold the user's:

```python
result = remove_job(project, '<job id>')
```

To change something, edit `film.json`, run `plan.py`, and call `build_film` again, then look again. If you rendered, remove the job first. Run `templates.py` again too if the brand or `fps` changed. If the user has edited the timeline by hand, ask before rebuilding, or make the change by hand on the timeline.

## Finish

Leave saving to the user unless they ask, because saving also commits any other unsaved edits they have open. Report:

- the timeline and bin, and the tracks
- where the titles were installed
- that the new timeline is now the current one, naming the one `preflight` found open, and, if you rendered, that the render settings changed
- any caption wording you inferred, and anything in the screenshots that conflicts with the brief
- what you checked, and what you didn't. Frames show the picture, but not motion or how the Inspector and timeline look in Resolve.
- anything approximated, and these limits: no audio, stills only, and highlights that stay on the frame during camera moves

Clips come from their files on disk, so moving the film's folder or the screenshots takes the clips offline. Keep `build/assets/` too, since the cursor and backdrops live there.

To remove a brand's titles from the Effects Library, run `templates.py "<WORK>" --uninstall`. It only removes that brand's four files. Timelines already built keep their own copies: a render after removing them came out identical.
