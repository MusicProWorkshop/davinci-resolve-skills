# film.json

A film is a folder holding `film.json`. Relative paths are from that folder, and the build writes into its `build/`. Each film gets its own folder.

- Times are seconds, counted from the start of the scene.
- Positions are pixels on the 1920x1080 frame, as the screenshot looks at zoom 1, whatever the image's own size. `scripts/measure.py` works in these coordinates.

## Film

| Key | Default | Meaning |
| --- | --- | --- |
| `name` | required | Timeline name |
| `bin` | `Tutorials` | Media pool folder, as `A/B`. The film gets a bin named after it inside. |
| `fps` | `60` | Whole number. Tested at 30 and 60. It can differ from the project's rate, and the timeline then has its own rate setting. Use the project's unless there's a reason not to. |
| `transition` | `0.4` | Dissolve length between all scenes. `0` gives hard cuts. |
| `ease` | `[0.45, 0, 0.2, 1]` | Default curve for moves, as a CSS cubic-bezier |
| `click` | | Every ripple's `size` (140), `thickness` (7) and `color` (the accent) |
| `focusY` | `470` | Height on the frame where a camera `rect` is centered. It sits above the middle so captions don't cover the subject. |
| `brand` | see below | An object, or a path to a JSON file so several films can share one |
| `scenes` | required | In order. Neighbouring scenes overlap by `transition`, so the film is shorter than the sum of `seconds`. |

## Brand

```json
{
  "prefix": "Acme",
  "folder": "Acme",
  "font": "Lato",
  "styles": { "regular": "Regular", "bold": "Bold", "black": "Black" },
  "colors": { "accent": "#f57c00", "page": "#0e1620", "subtle": "#a9b6c4", "logo": "#f7f5f2", "text": "#ffffff", "badgeText": "#10161f", "chip": "#172431" },
  "labels": [ { "name": "Host", "color": "#f57c00" }, { "name": "Attendee", "color": "#4aa8ff" } ],
  "wordmark": "Acme",
  "logoBars": [ { "x": 0, "h": 144 }, { "x": 42, "h": 78, "color": "#f57c00" } ]
}
```

- `prefix` names the titles (`Acme Caption`), and `folder` is their folder in the Effects Library. Everything is optional. Pick a prefix of your own for each brand, so one brand's titles don't replace another's.
- `font` and `styles` must be names Fusion knows, and `fonts_available` lists a family's styles. `wordmarkFont` and `wordmarkStyle` set a different font for the wordmark. Set `fontFile` to the path of the bold font file if `plan.py` says it can't find one. It's used for chips and to measure text.
- `labels` become the choices in the caption's Label menu, after None and before Step.
- `wordmark` is text on the cards. `logoBars` draws a simple logo of rounded bars that grow in. Each bar is 32 units wide, with `x` its left edge and `h` its height in the same units, and `color` defaulting to `colors.logo`. The logo draws at 0.6 px per unit. For any other logo, give the card an `overlays` entry with a PNG.

## Scenes

With dissolves on, each scene's clips and titles run between the middle of its two dissolves. So a caption, cursor or highlight ends at the middle of the dissolve out, even if its time runs later, and a card after the first starts at the cut, so its text animates half a dissolve late. Scene labels and overlays with `fadeIn` or `fadeOut` are the exception: they can run under the whole dissolve.

### Card

```json
{ "kind": "card", "name": "Title", "seconds": 3, "headline": "Getting Started", "line": "Set up your first project" }
```

Text is 132 px and 56 px, so a headline fits about 28 characters. `plan.py` warns when it doesn't. A card can also take `overlays`.

### Screen

`seconds` and `name` plus any of these. A scene needs `shots`, a `backdrop`, or both.

```json
{
  "name": "Open the panel", "seconds": 8,
  "label": "Host",
  "shots": [ { "file": "shots/panel.png", "at": 0 }, { "file": "shots/panel-open.png", "at": 3.2 } ],
  "camera": [
    { "at": 0, "zoom": 1 },
    { "at": 1, "dur": 1.2, "zoom": 1.8, "rect": { "x": 1200, "y": 300, "w": 400, "h": 120 } }
  ],
  "cursor": [
    { "at": 0, "point": { "x": 900, "y": 500 } },
    { "at": 1.5, "dur": 1, "point": { "x": 1400, "y": 360 } }
  ],
  "clicks": [ 2.8 ],
  "highlights": [ { "from": 2.4, "to": 5, "rect": { "x": 1200, "y": 300, "w": 400, "h": 120 } } ],
  "captions": [ { "from": 0.3, "to": 7.5, "text": "Click Open Panel" } ]
}
```

| Key | Meaning |
| --- | --- |
| `shots` | Stills in order, each until the next one's `at`. They must be 16:9. Capture at twice the frame or more, so zooming stays sharp. |
| `backdrop` | A colour, as `"#0e1620"`, under everything |
| `camera` | The first cue is where the scene starts, and later ones move from there. A cue's `dur` defaults to 1 s. `zoom` plus an optional `rect` to center on, or `translate: [tx, ty]` for exact placing as `x' = tx + x * zoom`. See below for how `rect` places it. |
| `cursor` | The first cue is where it fades in, at that cue's `at`, and later ones move it, with `dur` defaulting to 1 s. `point` is on the screenshot, so the cursor follows camera moves. It stays until the scene ends. |
| `clicks` | Times. Each gives a ripple at the cursor and a press of the cursor. Needs `cursor`. |
| `highlights` | `from`, `to`, `rect`, and optionally `pad` (6), `thickness` (3), `radius` (10), `glow` (22), `color`. `rect` is on the screenshot, and the numbers are in screenshot pixels, so they grow with the camera's zoom. For a small button at 2x, try `pad: 4` and `glow: 12`, because the default glow tints the button. |
| `captions` | `from`, `to`, `text`, and optionally `label` or `step` for that caption. Times past the scene's end are cut to fit. |
| `label` | A brand label for the scene's captions |
| `step` | A number from 1 to 9 for the scene's captions, shown in a badge |
| `chip` | `{ "from", "to", "text", "icon" }`: a dragged-file chip that follows the cursor. A PNG, so its text can't be edited in Resolve. |
| `overlays` | Images fixed on the frame. See below. |
| `labels` | Labels without a caption bar: `{ "label", "x", "y", "anchor", "from", "to" }`. `x`, `y` are the middle of the badge. `anchor: "right"` makes `x` its right edge. They default to the whole scene and fade with the dissolves. |

With `rect`, the camera computes, where `cx`, `cy` is the middle of `rect` (or the middle of the frame with no `rect`):

```
tx = clamp(960 - cx * zoom, 1920 - 1920 * zoom, 0)
ty = clamp(focusY - cy * zoom, 1080 - 1080 * zoom, 0)
```

Any cue in `camera` or `cursor` can take its own `ease`. A move stays as two keyframes with handles when its curve starts and ends flat (`[a, 0, b, 1]`), or two plain keyframes when linear (`[0, 0, 1, 1]`). Other curves are sampled every 0.05 s. So is a move that overlaps another or crosses a shot change. For a curve no bezier fits, such as a spring, write a run of short linear cues.

The ring's stroke is centered on the edge of `rect` plus `pad`, and its glow spreads both inwards and outwards. To match a CSS border, which sits inside its box, use `pad - thickness / 2` and `radius - thickness / 2`.

**Highlights don't follow the camera.** They are titles placed on the frame at the zoom when they start. `plan.py` moves a highlight's start to after a camera move, ends it before the next, and warns when that costs more than 0.25 s. If the highlight has to appear sooner, make the camera arrive sooner.

### Overlays

```json
{ "file": "player.png", "from": 0, "to": 1, "x": 324, "y": 70, "width": 1500, "crop": { "x": 0, "y": 180, "w": 1920, "h": 720 }, "fadeIn": 0.4, "fadeOut": 0.4 }
```

Everything but `file` is optional. `crop` is the part to show, in pixels of the image as it fills the frame. Without it, that's the whole image. `x`, `y` are where its top left lands and `width` is its size on the frame. Without them, it stays where Resolve fits it. Overlays that overlap in time get separate tracks automatically. Corners stay square.

## What the build refuses

`plan.py` stops with a message on a missing file, a shot that isn't 16:9, an unknown label, clips that overlap on a track (two captions at once, say), or clicks with no cursor. It warns about soft shots, text that may run off the frame, and highlights moved by the camera.
