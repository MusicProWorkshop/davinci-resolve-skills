"""Reviews a render: a contact sheet per scene, and with a reference video, SSIM per scene and side-by-side frames.

    python review.py <work> <render> [reference video] [--at <seconds>,<seconds>...]

Writes <work>/build/review/sheet-*.jpg, and with a reference, ssim-by-half-second.txt. Without a reference, the sheets show each scene,
the middle of each highlight and just after each click. Frames that are nearly one colour are flagged, since a broken comp often renders
black. --at writes just those moments, in timeline seconds, at full size.
"""
import json
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageStat

COMPARE_FPS = 30


CELL = (960, 540)


def grab(src, seconds, path):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{seconds:.3f}", "-i", src, "-frames:v", "1", "-vf", f"scale={CELL[0]}:{CELL[1]}", path], check=True)
    return Image.open(path).convert("RGB")


def moments(plan):
    """The frames worth checking by eye: each highlight in its middle, and just after each click."""
    fps = plan["fps"]
    rows = []
    for title in plan["titles"]:
        kind = title["template"].rsplit(" ", 1)[-1]
        if kind == "Highlight":
            rows.append(((title["start"] + title["end"]) / 2 / fps, "highlight"))
        elif kind == "Click":
            rows.append(((title["start"] + fps * 0.1) / fps, "click"))
    return rows


def full_size(render, reference, seconds, out_dir):
    """One moment at full size, for differences too small for the sheets. With a reference, Resolve is on top."""
    rows = []
    for src in [render] + ([reference] if reference else []):
        path = os.path.join(out_dir, "frame.png")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{seconds:.3f}", "-i", src, "-frames:v", "1", path], check=True)
        rows.append(Image.open(path).convert("RGB"))
    sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)))
    y = 0
    for row in rows:
        sheet.paste(row, (0, y))
        y += row.height
    os.remove(os.path.join(out_dir, "frame.png"))
    out = os.path.join(out_dir, f"at-{seconds:.2f}.png")
    sheet.save(out)
    print(out)


def main(work, render, reference=None, at=None):
    work, render = os.path.abspath(work), os.path.abspath(render)
    reference = os.path.abspath(reference) if reference else None
    with open(os.path.join(work, "build", "plan.json"), encoding="utf8") as f:
        plan = json.load(f)
    fps = plan["fps"]
    out_dir = os.path.join(work, "build", "review")
    os.makedirs(out_dir, exist_ok=True)
    if at is not None:
        for seconds in at:
            full_size(render, reference, seconds, out_dir)
        return
    marks = plan["markers"] + [{"frame": plan["total"], "name": "(end)"}]
    samples = []
    if reference:
        # Run from out_dir, because ffmpeg's filter syntax can't take a drive letter's colon cleanly.
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", render, "-i", reference, "-lavfi",
                        f"[0:v]fps={COMPARE_FPS},format=yuv420p[a];[1:v]fps={COMPARE_FPS},format=yuv420p[b];[a][b]ssim=stats_file=ssim.txt", "-f", "null", "-"], check=True, cwd=out_dir)
        with open(os.path.join(out_dir, "ssim.txt")) as f:
            scores = [float(m.group(1)) for m in re.finditer(r"All:([0-9.]+)", f.read())]
        print(f"frames compared {len(scores)} of {plan['total'] * COMPARE_FPS // fps}, mean SSIM {sum(scores) / len(scores):.4f}")
        step = COMPARE_FPS // 2
        with open(os.path.join(out_dir, "ssim-by-half-second.txt"), "w") as f:
            for s in range(0, len(scores), step):
                part = scores[s:s + step]
                f.write(f"{s / COMPARE_FPS:8.2f}s  mean {sum(part) / len(part):.4f}  low {min(part):.4f}\n")
    for a, b in zip(marks, marks[1:]):
        # On a frame of the comparison rate, so both videos show the same moment.
        samples.append((round((a["frame"] + b["frame"]) / 2 / fps * COMPARE_FPS) / COMPARE_FPS, a["name"]))
        if reference:
            first, last = a["frame"] * COMPARE_FPS // fps, b["frame"] * COMPARE_FPS // fps
            part = scores[first:last] or [0]
            low = min(range(len(part)), key=part.__getitem__)
            print(f'{a["name"]:<28} mean {sum(part) / len(part):.4f}  low {part[low]:.4f} at {(first + low) / COMPARE_FPS:.2f}s')
            samples.append(((first + low) / COMPARE_FPS, a["name"] + " (lowest)"))
    if not reference:
        samples += moments(plan)
        samples.sort()
    rows, flat = [], []
    temp = os.path.join(out_dir, "frame.png")
    for seconds, name in samples:
        row = Image.new("RGB", (CELL[0] * (2 if reference else 1), CELL[1]), "black")
        frame = grab(render, seconds, temp)
        if max(ImageStat.Stat(frame).stddev) < 3:
            flat.append(f"{name} at {seconds:.2f}s")
        row.paste(frame, (0, 0))
        if reference:
            row.paste(grab(reference, seconds, temp), (CELL[0], 0))
        draw = ImageDraw.Draw(row)
        tag = f"{name} {seconds:.2f}s"
        draw.rectangle((0, 0, 8 + draw.textlength(tag), 16), fill="black")
        draw.text((4, 3), tag, fill="yellow")
        rows.append(row)
    os.remove(temp)
    per = 6
    columns = 1 if reference else 2
    count = 0
    for s in range(0, len(rows), per):
        chunk = rows[s:s + per]
        lines = (len(chunk) + columns - 1) // columns
        sheet = Image.new("RGB", (chunk[0].width * columns, CELL[1] * lines))
        for i, row in enumerate(chunk):
            sheet.paste(row, ((i % columns) * row.width, (i // columns) * CELL[1]))
        sheet.save(os.path.join(out_dir, f"sheet-{count:02d}.jpg"), quality=85)
        count += 1
    print(f"sheets: {count} in {out_dir}")
    for row in flat:
        print("NEARLY ONE COLOUR:", row)


if __name__ == "__main__":
    args = sys.argv[1:]
    moment = None
    if "--at" in args:
        i = args.index("--at")
        moment = [float(v) for v in args[i + 1].split(",")]
        del args[i:i + 2]
    main(*args, at=moment)
