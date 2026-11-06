"""Finds positions on a screenshot for film.json. All coordinates are pixels on the 1920x1080 frame, whatever the image's size.

    python measure.py grid <image> <out.png>                 the image at 1920x1080 with a labelled grid, to read rough positions from
    python measure.py at <image> <x> <y> [tolerance]         the rectangle of the flat-coloured element under that point, such as a button
    python measure.py show <image> <out.png> <x,y,w,h> ...   the image with rectangles drawn on it, to check them before building

"at" spreads out from the point through similar colour, going around text and icons. Pick a point on the element's fill, not on its text.
Tolerance defaults to 18. Lower it if the rectangle takes in a neighbour of a similar colour.
"""
import json
import sys
from collections import deque

from PIL import Image, ImageDraw

W, H = 1920, 1080


def load(path):
    return Image.open(path).convert("RGB").resize((W, H), Image.LANCZOS)


def grid(path, out):
    image = load(path)
    draw = ImageDraw.Draw(image, "RGBA")
    for x in range(0, W, 100):
        draw.line([(x, 0), (x, H)], fill=(255, 255, 0, 150 if x % 500 == 0 else 60))
        draw.rectangle((x + 1, 1, x + 34, 12), fill=(0, 0, 0, 200))
        draw.text((x + 3, 1), str(x), fill="yellow")
    for y in range(0, H, 100):
        draw.line([(0, y), (W, y)], fill=(255, 255, 0, 150 if y % 500 == 0 else 60))
        draw.rectangle((1, y + 1, 34, y + 12), fill=(0, 0, 0, 200))
        draw.text((3, y + 1), str(y), fill="yellow")
    image.save(out)
    print(out)


def at(path, x, y, tolerance=18):
    image = load(path)
    pixels = image.load()
    target = pixels[x, y]
    seen = {(x, y)}
    queue = deque(seen)
    left, top, right, bottom = x, y, x, y
    while queue:
        px, py = queue.popleft()
        left, top, right, bottom = min(left, px), min(top, py), max(right, px), max(bottom, py)
        for nx, ny in ((px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)):
            if 0 <= nx < W and 0 <= ny < H and (nx, ny) not in seen:
                if all(abs(a - b) <= tolerance for a, b in zip(pixels[nx, ny], target)):
                    seen.add((nx, ny))
                    queue.append((nx, ny))
    rect = {"x": left, "y": top, "w": right - left + 1, "h": bottom - top + 1}
    print(json.dumps(rect), "colour", "#%02x%02x%02x" % target)
    if len(seen) > W * H * 0.25:
        print("WARNING: that's a large area, probably the page's background rather than an element")
    elif rect["w"] * rect["h"] > len(seen) * 3:
        print("WARNING: the area is much bigger than the colour it found, so it may have leaked along a border or into a neighbour. Lower the tolerance, and check with show.")


def show(path, out, rects):
    image = load(path)
    draw = ImageDraw.Draw(image)
    for row in rects:
        x, y, w, h = [float(v) for v in row.split(",")]
        draw.rectangle((x, y, x + w - 1, y + h - 1), outline="#ff00ff", width=2)
    image.save(out)
    print(out)


if __name__ == "__main__":
    command, image_path, *rest = sys.argv[1:]
    if command == "grid":
        grid(image_path, rest[0])
    elif command == "at":
        at(image_path, int(rest[0]), int(rest[1]), *(int(v) for v in rest[2:3]))
    elif command == "show":
        show(image_path, rest[0], rest[1:])
    else:
        raise SystemExit(__doc__)
