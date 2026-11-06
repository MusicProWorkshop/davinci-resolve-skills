# How the build works, and what goes wrong

Read this if a step fails, if you change the scripts, or if Resolve is newer than 21.2. Everything here was found on Resolve Studio 21.1.1 on Windows, and the build was checked again on 21.2: the `.drt` layout is unchanged, and the render matched 21.1.1's exactly.

## Why a patched .drt

| Way in | Result |
| --- | --- |
| Scripting API | No Inspector keyframes, still true in 21.2. In 21.1.1 there was also no way to set a title's length or track. 21.2's `SetPosition`, `MoveItems` and `SetRightOffset` may cover that, but titles still go in the `.drt` because clips have to anyway |
| FCPXML import | Drops keyframes |
| FCP7 XML import | Keeps keyframes, but only some of the easing handles |
| Patched `.drt` | Keyframes with handles, and titles at exact frames and lengths |

So the build imports FCP7 XML to get clips into the media pool, exports that as a `.drt`, writes the keyframes and titles into it, and imports the result. The API then does what it can: title text, values that don't animate, crops, fades, dissolves, track names, markers. The finished timeline is ordinary and doesn't depend on any of this.

## The .drt format

Undocumented, and may change. A `.drt` is a zip of XML.

- A clip's `EffectFiltersBA` is hex of `00000002`, a big-endian length, then protobuf: raw after byte `0x80`, zstd after `0x81`.
- Field 1 is a filter: its field 1 is the filter type (Transform is 4), and repeated field 9 is its parameters, by position. An unset parameter is an empty field 9.
- A parameter has field 1 = id, field 3 = `{ 1: { 2: double } }` for its static value, field 10 = its keys.
- Ids and slots: ZoomX 42 slot 0, ZoomY 43 slot 1, Pan 40 slot 3, Tilt 41 slot 4. Pan and Tilt are fractions of the frame (px/1920, px/1080).
- Keys are a big-endian `-(byte length)`, then records of int32le frame, 2 zero bytes, uint16le flags, then doubles. Flags `0x0c`: value. Flags `0x0d`: value, in x, in y, out x, out y, 0, 0. Handles are offsets in frames and in value.
- Key times count from the source, so a clip's `in` is the scene-local frame it starts on.
- A title's `CompositionBA` is 4 bytes, then zlib of the comp. Its `TEMPLATE_ID` names the template.

If `patch_drt.py` fails on a later Resolve, export a clip with a known keyframe from the Inspector as a `.drt` and compare it with this layout.

## Traps

- **Static values in the blob are ignored on import.** Set them with `SetProperties` after import, as `finish_batch` does.
- **A title's comp only exports with data once it has been opened.** `make_blueprint` calls `GetToolList` on each for that reason.
- **Clips can link to another bin's copy.** Importing a file that's already in the media pool can link to the existing item in any bin, not a new one in the film's bin. Deleting that other bin takes the clip offline. Before deleting any bin, check that no timeline uses its clips, and leave the bin alone if you can't. `verify` reports clips whose media is gone.
- **Images that aren't 16:9.** Resolve measures Pan, Tilt and crop against the fitted image rather than the frame, so `plan.py` pads overlays onto a clear 16:9 canvas first.
- **Another frame rate.** FCP7 XML at a different rate from the project imports as a timeline with its own rate setting (`useCustomSettings` is on). Tested at 30 fps in a 60 fps project. Other sizes than 1920x1080 are untested.
- **Dissolves are items.** `GetItemListInTrack` lists each transition as an item. They need even lengths and sit centered on the cut, so a shot's first frames play under the dissolve. That's why camera keys run from frame 0 of the scene.
- **Render settings.** A render changes the project's output folder and file name, and jobs the user queues later inherit them.
- **Fusion text.** `Text.Output.DataWindow[3] - [1]` measures text, but a Text+ can't read that in its own Center, because it's a cycle and the render fails. A Transform after it does the placing. A mask's output is named `Mask`, not `Output`, and wiring `Output` floods the frame with colour. `RectangleMask` Height is a fraction of frame height, and `EllipseMask` Height is a fraction of frame width.
- **`ExportCurrentFrameAsStill` races Fusion** and returns black or stale frames. Don't use it.
- **`Timeline.ExportFrame` and `ExportThumbnails` (21.2) are reliable.** 24 frames of titles, clicks and camera moves each matched the render of the same frame, at an SSIM of 0.991 or more. `review_frames` uses them.
- **They need the current timeline.** On a timeline that hasn't been opened, they return a black frame and still report success. `review_frames` makes the film's timeline current first.
- **New titles take a moment (21.2).** Titles installed while Resolve is running were not insertable for a few seconds. `make_blueprint` retries for about 12 s.
- **After `StopRendering`,** `AddRenderJob` returns `None` for 20 to 40 s. Wait, then call it again.
- **If calls start returning `None`** with no render running, a dialog is probably open in Resolve. Ask the user to look.
