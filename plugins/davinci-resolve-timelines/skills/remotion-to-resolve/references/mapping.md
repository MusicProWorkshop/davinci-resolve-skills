# From Remotion to film.json

## Building blocks

| In the Remotion code | In film.json | Notes |
| --- | --- | --- |
| `<Composition>` `fps` | `fps` | Whole numbers only |
| `<Composition>` `width`, `height` | Positions | 16:9 only. Multiply positions by `1920 / ` the width of the space they're written in. That may be the screenshot's capture width and not the composition's, so read how the component scales them. |
| `<Series.Sequence durationInFrames>` | A scene's `seconds` | `frames / fps` |
| `<TransitionSeries>` with `fade()` and `linearTiming` | `transition`, and each scene's `seconds` | The same overlap rule, so sum minus overlaps. One length for the whole film. |
| `slide()`, `wipe()` and others | `transition` | Becomes a dissolve. Tell the user. |
| `<Sequence from>` inside a scene | `from`, `to`, `at` | Local to the scene, in seconds |
| Full-frame `<Img src={staticFile(...)}>` | `shots[].file` | Absolute path into `public/`. A shot must be 16:9. |
| CSS `transform` over the whole screenshot, driven by `interpolate` | `camera` | See the arithmetic below |
| `Easing.bezier(a, b, c, d)` | `ease: [a, b, c, d]` | |
| `Easing.linear` | `ease: [0, 0, 1, 1]` | |
| `Easing.inOut(...)` and others | Short linear cues, or the nearest bezier | Evaluate the real function |
| `spring()` | Short linear cues | Call the real `spring` from `remotion` |
| An SVG or image following a path | `cursor` | The engine draws its own arrow, so another cursor's art won't carry over |
| A ripple or pulse at the cursor | `clicks`, and `click` for its size, thickness and color | Set `click` from the code, because the defaults are stronger than most CSS ripples |
| A positioned box with a border or glow | `highlights` | `rect` on the screenshot, `thickness`, `radius`, `glow`, `color`. A CSS border needs the correction in `film-format.md`. |
| A dragged item following the cursor | `chip` | Text and an icon character, as a PNG |
| A bar of text along the bottom | `captions`, and `label` or `step` | One style, with brand colors |
| A big centered title | `kind: "card"` | Headline and line only |
| Smaller images, or a cropped part of one | `overlays` | Fixed on the frame, with fades and square corners. Animated size or position won't carry over. |
| `<Video>`, `<OffthreadVideo>` | Not handled | See below |
| `<Audio>` | Not handled | Add it on the timeline afterwards, and say so |
| Other animated drawing | Not handled | See below |

## What doesn't map

Offer the user these, in this order:

1. **A still from Remotion.** If the element's motion doesn't matter, render it with `npx remotion still --frame=<n>` on a transparent background and use it as an overlay. Stills in a run of short overlays can stand in for slow change, as one per second did for two video players.
2. **Add it by hand afterwards.** Render just that element with a transparent background (`--codec=prores --prores-profile=4444`) and place it on a free track after the build. The build doesn't do this, and it hasn't been tested, so check the result in a render.
3. **Leave it out,** and say so in the report.

## Arithmetic

**Time.** `seconds = frames / fps`, local to the scene. If timing is in frames in the code, convert in the adapter, not by hand.

**Camera.** `translate: [tx, ty]` with `zoom` means a screenshot point `x` lands at `tx + x * zoom`, on the 1920x1080 frame. That equals CSS `transform: translate(tx, ty) scale(zoom)` with `transform-origin: 0 0`. With the default `transform-origin: center`:

```
tx = cssX + 960 * (1 - zoom)
ty = cssY + 540 * (1 - zoom)
```

Use `rect` only if the code centers on a rectangle with the same formula as the engine, which is in `film-format.md`. Otherwise use `translate`, and run the code's own calculation in the adapter.

**Overlapping moves.** The engine blends cues the way chained `interpolate` calls do when each starts from the current value. If the code does something else, compute the values and write short linear cues.

**Springs and other curves.** Sample the real function, about every 3 frames at 30 fps, and write a linear cue between each pair of samples:

```js
import { spring } from "remotion";
const value = (f) => spring({ frame: f, fps, config });
for (let f = 0; f < length; f += 3) {
  const zoom = 1 + (target - 1) * value(f + 3);
  cues.push({ at: (start + f) / fps, dur: 3 / fps, zoom, translate: place(zoom), ease: [0, 0, 1, 1] });
}
```

## Adapter skeleton

esbuild bundles the TypeScript data so plain Node can import it. It usually comes with Remotion's own packages. If it can't be found, use `npx esbuild` or add it as a dev dependency with the user's agreement.

```js
// resolve/<composition id>/export-film.mjs: writes film.json from the video's own data.
import { build } from "esbuild";
import { rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const project = resolve(here, "../..");
const bundle = join(here, ".bundle.mjs");
const source = (file) => JSON.stringify(join(project, file).replaceAll("\\", "/"));

// Font loaders run on import and need a browser, so they're replaced with nothing. Add any other package that does the same.
const noFonts = {
  name: "no-fonts",
  setup(b) {
    b.onResolve({ filter: /^@remotion\/(fonts|google-fonts)/ }, (args) => ({ path: args.path, namespace: "stub" }));
    b.onLoad({ filter: /.*/, namespace: "stub" }, () => ({ loader: "js", contents: "const none = () => ({ loaded: () => Promise.resolve() }); export const loadFont = none; export default { loadFont: none };" }));
  },
};

await build({
  stdin: { contents: `export * as scenes from ${source("src/scenes.ts")}; export * as theme from ${source("src/theme.ts")};`, resolveDir: project, loader: "ts" },
  bundle: true, format: "esm", platform: "node", outfile: bundle, logLevel: "error", plugins: [noFonts],
});
const { scenes: data, theme } = await import(pathToFileURL(bundle).href);
rmSync(bundle);

const fps = 30;                                    // from the composition
const asset = (file) => join(project, "public", file);
const scale = 1920 / data.WIDTH;                   // when the stage isn't 1920 wide
const rect = (r) => ({ x: r.x * scale, y: r.y * scale, w: r.w * scale, h: r.h * scale });

const filmScenes = data.SCENES.map((s) => ({
  name: s.name,
  seconds: s.durationInFrames / fps,
  shots: s.shots.map((shot) => ({ file: asset(shot.file), at: shot.at })),
  camera: s.camera.map((c) => ({ ...c, rect: c.rect && rect(c.rect) })),
  captions: s.captions,
}));

writeFileSync(join(here, "film.json"), JSON.stringify({
  name: "My Video (Resolve)",
  bin: "Remotion",
  fps: 60,
  transition: data.TRANSITION_FRAMES / fps,
  brand: { prefix: "My Brand", font: "Lato", colors: { accent: theme.COLORS.accent } },
  scenes: [
    { kind: "card", name: "Title", seconds: data.TITLE_FRAMES / fps, headline: "Title", line: "Subtitle" },
    ...filmScenes,
    { kind: "card", name: "End", seconds: data.END_FRAMES / fps, headline: "Thanks", line: "" },
  ],
}, null, 1));
```

The names here are examples, so match them to the project. If a data file imports `remotion` or React, bundling normally still works. If importing crashes on something browser-only, stub that package the way `noFonts` does.

Check the total before building: `plan.py` prints the length, and it should match `durationInFrames / fps`. A mismatch means scene lengths or overlaps are wrong.

`fps` may be higher than the composition's, because film times are in seconds. The composition's 30 fps moves stay the same on a 60 fps timeline, and the camera eases more smoothly.
