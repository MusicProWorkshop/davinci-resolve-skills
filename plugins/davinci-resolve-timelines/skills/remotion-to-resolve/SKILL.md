---
name: remotion-to-resolve
description: Convert a Remotion video's code into an editable DaVinci Resolve timeline, using real Inspector keyframes for screenshot camera moves, Fusion titles for captions, cards and highlights, and the same scene timing, then check the render against the Remotion render frame by frame. Use this whenever someone wants a Remotion composition, code-made tutorial or walkthrough rebuilt, recreated or edited in DaVinci Resolve, or wants to hand one to an editor, even if they only say "put this video on a timeline" or "use the Resolve integration" for a video made with Remotion or React. Works best on videos built from screenshots or images. Needs the resolve-screen-tutorial skill and DaVinci Resolve Studio with its MCP scripting tools.
---

# Remotion video to Resolve timeline

Reads a Remotion project, writes a small adapter that turns its scene data into the `film.json` that the `resolve-screen-tutorial` skill builds from, runs that build, and compares the result with the Remotion render.

It's a rebuild with Resolve's tools, not a copy of the pixels. React can draw anything, while the timeline has images, keyframes and Fusion titles. So the honest part of this job is telling the user what maps cleanly, what's approximated, and what doesn't carry over.

## Before you start

- `resolve-screen-tutorial` sits next to this skill's folder. Read its `SKILL.md` and `references/film-format.md` now, since you'll write that format and follow those build steps. If it's missing, tell the user this skill needs it.
- The Remotion project has its dependencies installed. Its own code stays unchanged: the adapter only reads it.

## Steps

**1. Read the video.** Start at `src/Root.tsx` for the composition's id, `fps`, `width`, `height` and `durationInFrames`, then follow it through the scene components and their data. Ask which composition if there are several and the request doesn't say. Find every asset under `public/`.

**2. List what's on screen, and map it.** [references/mapping.md](references/mapping.md) has the table from Remotion's building blocks to `film.json`. Read it now. Sort each element into one of three groups:

- **Maps directly:** full-frame screenshots, camera moves, a cursor, rings, captions, title cards, fades.
- **Approximated:** other easing, other transitions, web fonts that aren't installed, elaborate caption styling.
- **Doesn't carry over:** charts, particles, 3D, Lottie, or text animated letter by letter.

If anything important is in the third group, tell the user before building and offer the choices in `references/mapping.md`. If the video is mostly in that group, this approach is the wrong fit, so say so instead of building a poor copy.

**3. Get a reference video.** Look for a render of this composition in `out/`. It's good if it's newer than the composition's own source files and has `durationInFrames` frames (check with `ffprobe`). A smaller web encode is fine, and only lowers the scores slightly. Otherwise render one, with the composition's own settings:

```bash
npx remotion render <composition id> out/<composition id>.mp4
```

**4. Write the adapter.** Put it in `<project>/resolve/<composition id>/export-film.mjs`, and have it write `film.json` beside it. That folder is the film's folder for the build. Add `build/` to the project's ignore list only if the user wants these files kept in the repository, and don't commit unless asked.

The adapter should import the video's real data, so that when the copy or timing changes, running it again carries the change across. `references/mapping.md` has a skeleton and the arithmetic. Only copy values by hand when they're tangled inside JSX, and tell the user which ones, since those won't follow later code changes.

Set the brand from the code's colors, fonts and logo. List every font the video loads and check each with `fonts_available`. If one isn't installed, ask whether to install it or use a similar installed one. An installed font with the same name can still be a different cut from the web font, with slightly different widths.

**5. Build.** Follow the Build section of `resolve-screen-tutorial`'s `SKILL.md` from step 1 to step 4, with `WORK` set to the film's folder. Step 4's `review_frames` is a quick check before you render. Then render, as in its step 5, because the comparison needs the whole video. Skip its `review.py` call, because step 6 here does that with the reference, and remove your render job once you're done comparing. Its decisions apply here too: tell the user which project this lands in, and never replace a timeline you didn't build. Set `fps` to the project's frame rate. Times in `film.json` are in seconds, so the timing still holds when it differs from the composition's.

**6. Compare with the Remotion render.** Pass the reference to `review.py`:

```bash
python "<resolve-screen-tutorial>/scripts/review.py" "<WORK>" "<WORK>/build/render/review.mp4" "<reference video>"
```

It prints SSIM (a similarity score where 1 is identical) for the film and each scene, with the frame where each scene is weakest. It writes side-by-side sheets to `build/review/`, Resolve on the left, and `ssim-by-half-second.txt`, which shows problems that a scene's lowest frame hides. Open the sheets. For a closer look, add `--at <seconds>` to get one moment at full size, Resolve on top.

As a guide, screenshot-based films rebuilt faithfully scored 0.96 to 0.97 overall. A scene well below its neighbours has a real difference, so look at its lowest frame:

| What you see | Usual cause |
| --- | --- |
| Everything offset or the wrong size | Scale or transform origin in the adapter |
| The whole film shifted in time | Scene starts or transition overlap in the adapter |
| Camera right at rest, wrong in motion | Easing |
| A ring slightly too big | CSS border sits inside its box, see `film-format.md` |
| Only text differs | Font: swapped, or the same name in a different cut |

Some differences are expected and don't need fixing:

- A highlight appears late, because it waits for the camera to stop.
- A ring's glow tints the inside of the ring, since a Fusion blur spreads both ways.
- Captions, cursor and rings end at the middle of a dissolve instead of staying on the outgoing scene.
- A card after the first animates half a dissolve late.

Fix the adapter, run it again, then run `plan.py` and `build_film` again. Stop when what's left is differences you can name.

**7. Report.** Everything in `resolve-screen-tutorial`'s Finish section, plus:

- the SSIM scores
- the list of differences from step 6, each with its cause
- anything from the "doesn't carry over" group and what you did about it
- where the adapter is, how to run it again, and that a rebuild replaces the timeline, losing edits made on it
