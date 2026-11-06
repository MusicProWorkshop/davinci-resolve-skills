# DaVinci Resolve Timelines

Claude Code skills that build timelines in DaVinci Resolve that an editor can keep working on. Camera moves are Inspector keyframes, and captions, highlights and cards are Fusion titles with controls in the Inspector.

| Skill | Builds a timeline from |
| --- | --- |
| `resolve-screen-tutorial` | Screenshots and a short brief: a software tutorial or product walkthrough with zooms, a cursor, click ripples, highlights, captions and title cards |
| `remotion-to-resolve` | A [Remotion](https://www.remotion.dev) video's code. It writes an adapter for the video's scene data, builds with `resolve-screen-tutorial`, and compares the render with the Remotion render frame by frame |
| `kinetic-film-to-resolve` | A kinetic typography film made with the `scenario-kinetic-film` skill: one Fusion comp per shot, on the film's beat grid |

You ask in plain words, such as "make a 30-second walkthrough of our settings page in Resolve from these screenshots", and Claude picks the skill.

## Install

In Claude Code:

```
/plugin marketplace add MusicProWorkshop/davinci-resolve-skills
/plugin install davinci-resolve-timelines@musicproworkshop-resolve
```

Or from a shell:

```bash
claude plugin marketplace add MusicProWorkshop/davinci-resolve-skills
claude plugin install davinci-resolve-timelines@musicproworkshop-resolve
```

To use a skill without the plugin system, copy its folder from `plugins/davinci-resolve-timelines/skills/` into `~/.claude/skills/`. `remotion-to-resolve` needs `resolve-screen-tutorial` copied beside it.

## Requirements

- **DaVinci Resolve Studio 21** with a project open, and its MCP server added to Claude Code. Resolve 21 ships it as `ResolveMCP.exe` in its install folder on Windows. The skills use its `run_script_unsafe` tool.
- **Python 3** with `pillow` on PATH, and **ffmpeg** on PATH.
- **Node.js** for `remotion-to-resolve`, inside the Remotion project, and for `kinetic-film-to-resolve`.
- **The `scenario-kinetic-film` skill** and a film made with it, for `kinetic-film-to-resolve`. It isn't part of this repository.

## What was tested

Everything was built and checked on Windows with DaVinci Resolve Studio 21.1.1 and 21.2, at 1920x1080. On 21.2 the skills review frames straight from the timeline, without rendering.

- **`resolve-screen-tutorial`:** tested at 60 fps, and at 30 fps inside a 60 fps project. Other sizes and macOS haven't been tested.
- **`remotion-to-resolve`:** rebuilt two Remotion tutorials with a similarity score (SSIM, where 1 is identical) of 0.96 to 0.97 against the Remotion renders.

**Known limits:**
- **Media:** stills only, and no audio.
- **Highlights:** they stay on the frame during camera moves, so they appear once the camera stops.
- **Resolve version:** `resolve-screen-tutorial` writes keyframes into Resolve's undocumented `.drt` timeline format. A later Resolve version could change it, and the skill's `references/how-it-works.md` explains how to check.

Each skill leaves saving the project to you, and changes the project's render settings when it renders a check.

## License

[MIT](LICENSE)
