# Fusion and Resolve scripting traps

Found on Resolve Studio 21.1.1 on Windows. Recheck them if a later version behaves differently.

## Comps

- **`comp.Lock()` while wiring gives a black clip.** Even with `Unlock()` afterwards, a comp whose MediaOut was connected while locked rendered black, while the same comp built unlocked was fine. Building unlocked is fast: 26 shots in about 20 s.
- **Setting a Loader's clip opens a modal "Open File" dialog** on most comps, and so does `comp.Loader({...})`. Wrap `AddTool('Loader')` and `Clip[1] = path` in `Lock()`/`Unlock()`, and do the rest of the wiring after unlocking. The script does not fail when this happens; later calls just start failing.
- **A file name ending in a digit is an image sequence.** `key1.png` and `key2.png` load as one 2-frame clip, so shots swap images or show only one logo piece, with no error. `Shot.loader` copies such stills to a `_still` name first.
- **`AddModifier` leaves a stray keyframe at frame 0** holding the current value. Without pinning, a `Blend` keyed 0 to 1 late in a shot starts at 1 and fades down. `key()` pins frame 0 to the first value.
- **`Transform.Center` is relative to its own canvas.** Moving a small solid with a Transform clips it. Use a full-frame solid with a RectangleMask, or animate the `Center` of a Merge, which is in frame space.
- **Clip length.** `InsertFusionCompositionIntoTimeline` gives no way to set a length, so shots use `AppendToTimeline` on a placeholder clip with `startFrame`/`endFrame`, then `AddFusionComp`. Starting at source frame 0 keeps the comp's own frames at 0 to duration - 1.
- **Tool IDs.** On 21.1.1, `CoordSpace` and `Duplicate` did not create tools with `AddTool`. On 21.2, `CoordSpace`, `Fuse.Duplicate` and `KD_Duplicate` do; `fu.GetRegList(1)` lists every ID. Rays stay thin lines rotated with Merge `Angle`: noise through `CoordSpace` gave stripes, not clean speed lines.
- **Krokodove tools take `Image`, not `Input`.** `KD_ChannelShifter` (the RGB split) connects with `ConnectInput('Image', ...)`; channel 1 is red and channel 3 is blue (`Center1`, `Center3`).

## Text

- **Text+ width.** For Lato Black, width in pixels at 1920 is about `Size * em width * 1249`. Oswald Bold came out about 8 % narrower with the same number, which is safe. `measure_fonts.py` supplies the em widths.
- **Outlines.** `Alpha2` did not fade them as expected. Ghost rows mix the ground and ink colours instead.
- **Text3D.** Shallow extrusion (`ExtrusionDepth` about .07) stays crisp. At .3 the sides blur the letter shapes, even with lights.
- **Typing** is the Text+ `End` input, keyed from 0 to 1.
- **Per-letter animation** is the `StyledTextFollower` modifier on `StyledText`. The text moves onto the Follower's own `Text` input, which must be set or the word goes blank. `Delay` is frames between letters; keyframe the Follower's `CharacterAngleZ` and `CharacterOffset`, and each letter plays them in turn.
- **Scramble** is the `TextScramble` modifier on `StyledText`: set `InputText`, `AnimateOnTime` = 1, and key `Randomness` from 1 to 0. `SubstituteChars` picks the glyphs.
- **Counting numbers** are a Text+ expression: `tool.StyledText.SetExpression('Text(string.format("%d", ...time...))')`. Lua's `string.format` and `math` work there.
- **Echo trails.** The Trails tool needs earlier frames, so a frame rendered alone shows no trail. Delayed copies through `TimeSpeed` (`Delay` in frames) render correctly on any frame.
- **Particles.** `pEmitter`'s default region is a point; set `SphereRgn.Size` to about 4 to fill the frame, `Style` to `ParticleStyleBlob` and `ParticleStyle.Size` to see them, and `pRender`'s `PreGenerateFrames` so they are already in the air on frame 0.

## Speed

- **Nested motion blur multiplies.** A blurred word under a blurred camera, or a blurred Renderer3D under a blurred camera, ran under 2 fps. Keep one blur per stack, and key the camera's `MotionBlur` input on for whips and hits only. With `blur='whips'`, hits skip it too, which heavy stages need.
- **Layer count matters most.** A shot with 42 animated LED layers took over 2 s per frame. One Text+ strip with a keyed `End` replaced them.
- **NVENC did not change those shots.** They crawled at the same rate on the software and NVIDIA encoders, because frame generation was the limit. Use the GPU encoder anyway, but look at the layers first.
- **Rendered speed** for a 29 s 1080p60 film: 3 to 4 minutes, of which the mock UI shots took much of the time.
- **Grain is the expensive look.** Fusion's Film Grain added about 0.75 s to a 0.15 s frame, and Resolve FX Film Grain inside a comp about the same. Glow (SoftGlow) adds about 0.05 s. The Fuse XGlow turned the frame pink and yellow at its defaults.
- **Frame exports time out at 10 s.** `ExportFrame`, `ExportThumbnails` and the MCP's `get_image` and `get_thumbnails` give up on a frame that takes longer. Once, after a heavy grid request on an 8 GB GPU that was nearly full, every later export and render failed, even on timelines with no Fusion, until Resolve was restarted. Ask for small sheets, and keep effects light.

## Reviewing

- **`ExportCurrentFrameAsStill` races Fusion.** It returned black frames, and identical frames for different times.
- **`Timeline.ExportFrame` and `ExportThumbnails` (Resolve 21.2) don't race Fusion.** Twelve frames of this skill's comps and 24 frames of Fusion titles and keyframed clips each matched the render of the same frame, at an SSIM of 0.99 or more. `frame_grid` uses them.
- **They need the current timeline.** On a timeline that hasn't been opened, they return a black frame and still report success. Call `project.SetCurrentTimeline` first, as `frame_grid` does.
- **Clip names (Resolve 21.2).** `TimelineItem.SetName` returns False for a name with any of `\ / : * ? " < > |`, and the clip keeps its media's name. `build_batch` drops those characters when that happens.
- **A render that takes 17 s for a whole film is a sign of black frames**, not success. Sample frames before quoting a time.

## Render queue

- **`StopRendering` takes time.** `IsRenderingInProgress` can stay true for 20 to 40 s, and `AddRenderJob` returns `None` until it clears, while `GetCurrentPage` returns `None`. Wait, then call it again.
- **The queue can hold the user's jobs.** Delete only jobs you added, by id.

## Recovering a stuck Resolve

If calls that should work start returning `None` or `False`, and `resolve.GetCurrentPage()` returns `None` with no render running, a dialog is probably open. Its title may not show as the main window's title, so list all the process's visible windows. On Windows, `EnumWindows` filtered by process id finds it, and posting `WM_CLOSE` (0x10) to a window titled "Open File" cancels it without taking focus. Close only dialogs your own script opened, and if you are unsure, ask the user to look at Resolve.
