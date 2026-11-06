# How each block converts

Each shot becomes one clip, so a `Words` block with five shots gives five clips. Every block here has been rendered in a whole film, except that `Picture` has only been tried with placeholder art.

## Close to the original

| Block | In Fusion |
| --- | --- |
| `Words` `cut`, `slam`, `stack`, `split`, `pair`, `punch3d` | Text+ with keyframed moves and outline ghost rows. `punch3d` is a 2D scale from depth, not extruded |
| `Strike` | NO + word over a native mock (`timeline`, `tiles`, `rack`), which dies on its beat |
| `Hero` | Real Text3D title, flying from depth and turning, with a typed line |
| `Fly` | Real Text3D words in depth, with a Camera3D flying through them |
| `Logo` | PNG pieces from the film's SVG drop in and wipe on; or a wiped wordmark when there is no logo file |

## Changed but recognisable

| Block or feature | What changes |
| --- | --- |
| `Stretch` | A horizontal scale, not the variable font's width axis, so letters distort |
| `Picture` | Pushes, pans, punches on words, hard-cuts to details. No weather layer |
| Whips | The camera throws the stage with motion blur over the ground |
| Exit `zoom` | A fast push into the word, not through a letter's counter |
| Exit `collapse` | The stage shrinks to a point |

## Fallbacks: much simpler than the original

These keep the words and the timing, and lose the signature move. Tell the user before building a film that leans on them, because they may want a custom comp for those shots.

| Block | Becomes |
| --- | --- |
| `Graph` | Label as a kicker over the big number. No drawn curve or portal |
| `Counters` | One kicker and big number per counter. No slot reels or code plane |
| `Progress` | Kicker and word. No conveyor or progress bar |
| `Chain` | One card per node. No comet ride |
| `Prompt` | Typed text on one card, ending in an accent flash. No keyword highlights or camera follow |
| `Notes` | One typed card per note. No preview or timeline reactions |
| `Rewind` | A title card. Reversing a copy of the earlier clips by hand gets closer |

## Not converted

HUD, karaoke captions, film grain and page bloom, RGB split and glitch, glyph scramble, code backdrops, typed note lines, mid-shot colour flips, weather. Sound effects are not placed: `cues` are in `film.json` if an editor wants them, and the music is handled by the audio step.

`setup` lists the ones that apply to the film as `notes`.
