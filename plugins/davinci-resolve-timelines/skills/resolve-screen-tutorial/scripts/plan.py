"""Turns <work>/film.json into a clip plan and an FCP7 XML.

    python plan.py <work>

Writes <work>/build/plan.json, <work>/build/film.xml and <work>/build/assets/*.png, and prints a summary and warnings.
The format of film.json is in references/film-format.md. Times in it are seconds from the start of the scene, and
positions are pixels on the 1920x1080 frame. A scene's cut sits in the middle of its dissolve.
"""
import json
import os
import re
import sys
from urllib.parse import quote
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
CAPTION_BAR_Y = H - 56 - 105 / 2  # middle of the caption bar when it has a label, as in templates.py
LAYER_ORDER = ["Screens", "Overlay", "Labels", "Highlights", "Chip", "Clicks", "Cursor", "Captions"]

DEFAULT_BRAND = {
    "prefix": "Tutorial", "font": "Lato", "styles": {"regular": "Regular", "bold": "Bold", "black": "Black"},
    "colors": {"accent": "#f57c00", "page": "#0e1620", "subtle": "#a9b6c4", "logo": "#f7f5f2", "text": "#ffffff", "badgeText": "#10161f", "chip": "#172431"},
    "labels": [], "wordmark": "", "logoBars": [],
}


def load_film(work):
    with open(os.path.join(work, "film.json"), encoding="utf8") as f:
        film = json.load(f)
    brand = film.get("brand", {})
    if isinstance(brand, str):
        with open(os.path.join(work, brand), encoding="utf8") as f:
            brand = json.load(f)
    merged = {**DEFAULT_BRAND, **brand}
    merged["styles"] = {**DEFAULT_BRAND["styles"], **brand.get("styles", {})}
    merged["colors"] = {**DEFAULT_BRAND["colors"], **brand.get("colors", {})}
    merged.setdefault("folder", merged["prefix"])
    film["brand"] = merged
    film.setdefault("fps", 60)
    film.setdefault("transition", 0.4)
    film.setdefault("ease", [0.45, 0.0, 0.2, 1.0])
    film.setdefault("focusY", 470)
    film.setdefault("bin", "Tutorials")
    return film


def font_file(family, style):
    folders = [os.path.join(os.environ.get("WINDIR", ""), "Fonts"), os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
               os.path.expanduser("~/Library/Fonts"), "/Library/Fonts", "/System/Library/Fonts"]
    wanted = re.sub(r"\W", "", family + style).lower()
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            stem, ext = os.path.splitext(name)
            if ext.lower() in (".ttf", ".otf") and re.sub(r"\W", "", stem).lower() == wanted:
                return os.path.join(folder, name)
    return None


def bezier(u, ease):
    x1, y1, x2, y2 = ease
    if u <= 0:
        return 0.0
    if u >= 1:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(40):
        t = (lo + hi) / 2
        x = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t ** 2 * x2 + t ** 3
        lo, hi = (t, hi) if x < u else (lo, t)
    t = (lo + hi) / 2
    return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t ** 2 * y2 + t ** 3


def blend(frame, cues):
    """Each cue moves from wherever the ones before it left the value, so overlapping moves mix."""
    value = list(cues[0]["value"])
    for cue in cues[1:]:
        p = bezier((frame - cue["from"]) / max(1e-9, cue["to"] - cue["from"]), cue["ease"])
        value = [v + (t - v) * p for v, t in zip(value, cue["value"])]
    return value


def clamp(v, lo, hi):
    return min(hi, max(lo, v))


def inspector(zoom, tx, ty):
    """A stage transform (x' = tx + x * zoom) as Inspector values: zoom about the frame's middle, Pan right, Tilt up, as fractions of the frame."""
    return {"zoom": zoom, "pan": (tx - W / 2 + W / 2 * zoom) / W, "tilt": (H / 2 - H / 2 * zoom - ty) / H}


def split_channels(keys, static):
    if keys is None:
        return {name: {"static": static[name]} for name in static}
    return {name: {"static": keys[0]["v"][name], "keys": [{**k, "v": k["v"][name]} for k in keys]} for name in static}


def fit_rect(size):
    """Where Resolve puts an image on the frame when it scales it to fit."""
    scale = min(W / size[0], H / size[1])
    w, h = size[0] * scale, size[1] * scale
    return {"x": (W - w) / 2, "y": (H - h) / 2, "w": w, "h": h}


class Planner:
    def __init__(self, work, film):
        self.work, self.film = work, film
        self.fps = int(film["fps"])
        self.brand = film["brand"]
        self.prefix = self.brand["prefix"]
        self.assets = os.path.join(work, "build", "assets")
        self.transition = self.frames(film["transition"])
        self.transition -= self.transition % 2
        self.half = self.transition // 2
        self.warnings = []
        self.scene_starts = []
        self.overlay_tracks, self.label_tracks, self.highlight_tracks = [], [], []
        self.labels = [row["name"] for row in self.brand["labels"]]
        self.step_index = len(self.labels) + 1
        self.bold = self.brand.get("fontFile") or font_file(self.brand["font"], self.brand["styles"]["bold"])
        if not self.bold:
            self.warnings.append(f'no font file found for {self.brand["font"]} {self.brand["styles"]["bold"]}, so text widths are not checked. Set "fontFile" in the brand to the bold file.')
        self.plan = {"name": film["name"], "bin": film["bin"], "fps": self.fps, "base": 3600 * self.fps, "brand_prefix": self.prefix,
                     "transition": self.transition, "clips": [], "titles": [], "cuts": [], "markers": []}

    def frames(self, seconds):
        return int(round(seconds * self.fps))

    def scaled(self, frames_at_60):
        """Animation lengths were tuned at 60 fps."""
        return int(round(frames_at_60 * self.fps / 60))

    def path(self, file):
        path = os.path.normpath(os.path.join(self.work, file))
        if not os.path.exists(path):
            raise SystemExit(f"missing file: {path}")
        return path

    def image_size(self, path):
        with Image.open(path) as image:
            return list(image.size)

    def title(self, template, track, start, end, name, inputs, fades=(0, 0)):
        if end <= start:
            self.warnings.append(f"{name} at frame {start} has no length left, so it was dropped")
            return None
        item = {"template": f"{self.prefix} {template}", "track": track, "start": start, "end": end, "fades": list(fades), "name": name, "inputs": inputs}
        self.plan["titles"].append(item)
        return item

    def free_track(self, tracks, stem, start, end):
        for i, used in enumerate(tracks):
            if not any(a < end and start < b for a, b in used):
                used.append((start, end))
                return f"{stem} {i + 1}"
        tracks.append([(start, end)])
        return f"{stem} {len(tracks)}"

    def text_width(self, text, px):
        if not self.bold:
            return None
        return ImageFont.truetype(self.bold, px).getlength(text)

    def label_index(self, name, scene_name):
        if name in (None, "None"):
            return 0
        if name not in self.labels:
            raise SystemExit(f'scene "{scene_name}": label "{name}" is not in the brand\'s labels {self.labels}')
        return self.labels.index(name) + 1

    def keys_for(self, values_at, moves, start, end):
        """Keyframes over [start, end]. A move wholly inside gets two keys, eased with handles when its curve starts and ends flat; anything else is sampled."""
        inside = sorted((m for m in moves if m["to"] > start and m["from"] < end), key=lambda m: m["from"])
        if not inside:
            return None
        merged = []
        for m in inside:
            if merged and m["from"] < merged[-1]["to"]:
                merged[-1]["to"] = max(merged[-1]["to"], m["to"])
                merged[-1]["sample"] = True
            else:
                flat = m["ease"][1] == 0 and m["ease"][3] == 1
                linear = m["ease"] == [0, 0, 1, 1]
                merged.append({"from": m["from"], "to": m["to"], "ease": m["ease"], "linear": linear,
                               "sample": m["from"] < start or m["to"] > end or not (flat or linear)})
        keys = []

        def add(key):
            if keys and keys[-1]["t"] == key["t"]:
                keys[-1].update(key)
            else:
                keys.append(key)

        for m in merged:
            a, b = max(m["from"], start), min(m["to"], end)
            if m["sample"]:
                f = a
                while f < b:
                    add({"t": f, "v": values_at(f)})
                    f += max(1, self.scaled(3))
                add({"t": b, "v": values_at(b)})
            elif m["linear"]:
                add({"t": a, "v": values_at(a)})
                add({"t": b, "v": values_at(b)})
            else:
                d = b - a
                add({"t": a, "v": values_at(a), "out": d * m["ease"][0]})
                add({"t": b, "v": values_at(b), "in": -d * (1 - m["ease"][2])})
        return keys

    def camera_cues(self, scene):
        cues = []
        for cue in scene.get("camera") or [{"at": 0, "zoom": 1}]:
            zoom = cue.get("zoom", 1)
            at = self.frames(cue["at"])
            if "translate" in cue:
                tx, ty = cue["translate"]
            else:
                rect = cue.get("rect")
                cx = rect["x"] + rect["w"] / 2 if rect else W / 2
                cy = rect["y"] + rect["h"] / 2 if rect else H / 2
                tx = clamp(W / 2 - cx * zoom, W - W * zoom, 0)
                ty = clamp(self.film["focusY"] - cy * zoom, H - H * zoom, 0)
            cues.append({"from": at, "to": at + self.frames(cue.get("dur", 1)), "value": [zoom, tx, ty], "ease": cue.get("ease", self.film["ease"])})
        return cues

    def cursor_cues(self, scene):
        return [{"from": self.frames(c["at"]), "to": self.frames(c["at"]) + self.frames(c.get("dur", 1)), "value": [c["point"]["x"], c["point"]["y"]],
                 "ease": c.get("ease", self.film["ease"])} for c in scene.get("cursor", [])]

    def scene(self, scene, start, head, tail, dur):
        if scene.get("kind") == "card":
            self.card(scene, start, head, tail, dur)
            return
        name = scene.get("name", "Scene")
        end_local = dur - tail
        cam = self.camera_cues(scene)
        moves = cam[1:]

        def cam_at(f):
            zoom, tx, ty = blend(f, cam)
            return inspector(zoom, tx, ty)

        shots = scene.get("shots", [])
        if not shots and not scene.get("backdrop"):
            raise SystemExit(f'scene "{name}" needs "shots" or a "backdrop"')
        if scene.get("backdrop"):
            self.clip_static("Screens", self.backdrop(scene["backdrop"]), start, head, end_local, inspector(1, 0, 0))
        peak = max(c["value"][0] for c in cam)
        for i, shot in enumerate(shots):
            path = self.path(shot["file"])
            size = self.image_size(path)
            if abs(size[0] / size[1] - W / H) > 0.01:
                raise SystemExit(f'{shot["file"]} is {size[0]}x{size[1]}. Shots must be 16:9, because the positions in film.json are on a full frame. Crop or pad it first.')
            if size[0] < W * peak * 0.9:
                self.warnings.append(f'{shot["file"]} is {size[0]} wide and scene "{name}" zooms to {peak:g}, so it will look soft. Capture it at {int(W * peak)} wide or more.')
            left = max(self.frames(shot.get("at", 0)), head)
            right = self.frames(shots[i + 1]["at"]) if i + 1 < len(shots) else end_local
            # The first shot shows from frame 0 during the dissolve in, and the last until the scene's end during the one out.
            key_left = 0 if i == 0 else left
            key_right = dur if i + 1 == len(shots) else right
            self.plan["clips"].append({"track": "Screens", "file": path, "size": size, "start": start + left, "in": left, "out": right,
                                       "transform": split_channels(self.keys_for(cam_at, moves, key_left, key_right), cam_at(left))})

        for overlay in scene.get("overlays", []):
            self.overlay(overlay, start, dur)
        for label in scene.get("labels", []):
            self.label(label, start, dur, name)
        for h in scene.get("highlights", []):
            self.highlight(h, start, head, end_local, cam, moves, name)
        self.captions(scene, start, head, end_local, name)
        self.pointer(scene, start, head, end_local, cam, moves)

    def card(self, scene, start, head, tail, dur):
        self.title("Card", "Screens", start + head, start + dur - tail, scene.get("name", "Card"),
                   {"Headline": {"StyledText": scene.get("headline", "")}, "Line": {"StyledText": scene.get("line", "")}})
        for overlay in scene.get("overlays", []):
            self.overlay(overlay, start, dur)
        if self.bold:
            width = self.text_width(scene.get("headline", ""), 132)
            if width > W - 120:
                self.warnings.append(f'the headline "{scene.get("headline")}" is about {int(width)} px wide at 132 px and will run off the frame')

    def clip_static(self, track, path, start, a, b, values, crop=None, fades=None):
        item = {"track": track, "file": path, "size": self.image_size(path), "start": start + a, "in": a, "out": b,
                "transform": {name: {"static": v} for name, v in values.items()}}
        if crop:
            item["crop"] = crop
        if fades and any(fades):
            item["fades"] = list(fades)
        self.plan["clips"].append(item)

    def backdrop(self, color):
        path = os.path.join(self.assets, f"backdrop-{color.lstrip('#').lower()}.png")
        Image.new("RGBA", (W, H), color).save(path)
        return path

    def overlay(self, o, start, dur):
        path = self.path(o["file"])
        size = self.image_size(path)
        fit = fit_rect(size)
        if abs(size[0] / size[1] - W / H) > 0.01:
            path = self.padded(path, size)
        rect = o.get("crop") or fit
        a, b = self.frames(o.get("from", 0)), self.frames(o["to"]) if "to" in o else dur
        width = o.get("width", rect["w"])
        scale = width / rect["w"]
        x, y = o.get("x", rect["x"]), o.get("y", rect["y"])
        crop = {"CropLeft": rect["x"], "CropRight": W - rect["x"] - rect["w"], "CropTop": rect["y"], "CropBottom": H - rect["y"] - rect["h"]}
        if not any(crop.values()):
            crop = None
        track = self.free_track(self.overlay_tracks, "Overlay", start + a, start + b)
        self.clip_static(track, path, start, a, b, inspector(scale, x - rect["x"] * scale, y - rect["y"] * scale), crop,
                         (self.frames(o.get("fadeIn", 0)), self.frames(o.get("fadeOut", 0))))

    def padded(self, path, size):
        """A copy on a clear 16:9 canvas. On other shapes, Resolve measures Pan, Tilt and crop against the fitted image rather than the frame."""
        width = max(size[0], round(size[1] * W / H))
        height = max(size[1], round(size[0] * H / W))
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        with Image.open(path) as image:
            canvas.paste(image.convert("RGBA"), ((width - size[0]) // 2, (height - size[1]) // 2))
        out = os.path.join(self.assets, "padded-" + os.path.splitext(os.path.basename(path))[0] + ".png")
        canvas.save(out)
        return out

    def label(self, row, start, dur, scene_name):
        a, b = self.frames(row.get("from", 0)), self.frames(row["to"]) if "to" in row else dur
        x = row["x"]
        anchor = row.get("anchor", "center")
        if anchor != "center":
            width = self.text_width(row["label"], 34)
            if width is None:
                raise SystemExit(f'anchor "{anchor}" needs the width of the text, and no file was found for {self.brand["font"]} {self.brand["styles"]["bold"]}. Set "fontFile" in the brand, or use anchor "center".')
            x += -(width + 52) / 2 if anchor == "right" else (width + 52) / 2
        track = self.free_track(self.label_tracks, "Labels", start + a, start + b)
        self.title("Caption", track, start + a, start + b, row["label"] + " Label", {
            "TextMain": {"StyledText": ""},
            "Pill": {"Label": self.label_index(row["label"], scene_name), "ShowBar": 0, "OffsetX": x - W / 2, "OffsetY": row["y"] - CAPTION_BAR_Y},
        }, (self.transition, self.transition))

    def highlight(self, h, start, head, end_local, cam, moves, scene_name):
        a, b = self.frames(h["from"]), self.frames(h["to"])
        asked = a
        for m in sorted(moves, key=lambda m: m["from"]):
            if m["from"] <= a < m["to"]:
                a = m["to"]
            if a < m["from"] < b:
                b = m["from"]
        a, b = max(a, head), min(b, end_local)
        if b <= a:
            self.warnings.append(f'scene "{scene_name}": the highlight at {h["from"]} s falls inside a camera move, so it was dropped')
            return
        if a - asked > self.fps / 4:
            self.warnings.append(f'scene "{scene_name}": the highlight at {h["from"]} s starts {(a - asked) / self.fps:.2f} s late, once the camera has stopped')
        z, tx, ty = blend(a, cam)
        r = h["rect"]
        pad = h.get("pad", 6)
        inputs = {
            "RingX": (r["x"] - pad) * z + tx, "RingY": (r["y"] - pad) * z + ty,
            "RingWidth": (r["w"] + pad * 2) * z, "RingHeight": (r["h"] + pad * 2) * z,
            "RingThickness": h.get("thickness", 3) * z, "RingRadius": h.get("radius", 10) * z, "RingGlow": h.get("glow", 22) * z,
        }
        if h.get("color"):
            c = h["color"].lstrip("#")
            inputs.update(TopLeftRed=int(c[:2], 16) / 255, TopLeftGreen=int(c[2:4], 16) / 255, TopLeftBlue=int(c[4:6], 16) / 255)
        track = self.free_track(self.highlight_tracks, "Highlights", start + a, start + b)
        self.title("Highlight", track, start + a, start + b, "Highlight", {"Ring": inputs}, (self.scaled(15), self.scaled(15)))

    def captions(self, scene, start, head, end_local, name):
        for c in scene.get("captions", []):
            a, b = max(self.frames(c["from"]), head), min(self.frames(c["to"]), end_local)
            label = c.get("label", scene.get("label"))
            step = c.get("step", scene.get("step"))
            if step is not None and label in (None, "None"):
                pill = {"Label": self.step_index, "StepNumber": step}
            else:
                pill = {"Label": self.label_index(label, name)}
            width = self.text_width(c["text"], 46)
            if width and width > W - 240:
                self.warnings.append(f'caption "{c["text"]}" is about {int(width)} px wide and may run off the frame, so shorten it')
            self.title("Caption", "Captions", start + a, start + b, "Caption", {"TextMain": {"StyledText": c["text"]}, "Pill": pill}, (self.scaled(18), self.scaled(12)))

    def pointer(self, scene, start, head, end_local, cam, cam_moves):
        cursor = self.cursor_cues(scene)
        if not cursor:
            if scene.get("clicks") or scene.get("chip"):
                raise SystemExit(f'scene "{scene.get("name")}" has clicks or a chip, but no "cursor" to place them at')
            return
        moves = cursor[1:] + cam_moves

        def screen_at(f):
            px, py = blend(f, cursor)
            zoom, tx, ty = blend(f, cam)
            return px * zoom + tx, py * zoom + ty

        def tip_at(f):
            sx, sy = screen_at(f)
            return {"pan": (sx - W / 2) / W, "tilt": (H / 2 - sy) / H}

        left = max(cursor[0]["from"], head)
        transform = split_channels(self.keys_for(tip_at, moves, left, end_local), tip_at(left))
        clicks = sorted(self.frames(c) for c in scene.get("clicks", []))
        zoom_keys = []
        press = self.scaled(12)
        for c in clicks:
            if left < c - 1 and c + press < end_local:
                zoom_keys += [{"t": c - 1, "v": 1.0}, {"t": c, "v": 0.82}, {"t": c + press - 1, "v": 0.82}, {"t": c + press, "v": 1.0}]
        transform["zoom"] = {"static": 1.0, "keys": zoom_keys} if zoom_keys else {"static": 1.0}
        path = os.path.join(self.assets, "cursor.png")
        self.plan["clips"].append({"track": "Cursor", "file": path, "size": [W, H], "start": start + left, "in": left, "out": end_local,
                                   "transform": transform, "fades": [self.scaled(15), self.scaled(12)]})
        for i, c in enumerate(clicks):
            limit = clicks[i + 1] if i + 1 < len(clicks) else end_local
            sx, sy = screen_at(c)
            inputs = {"ClickX": sx, "ClickY": sy}
            style = self.film.get("click", {})
            if "size" in style:
                inputs["ClickSize"] = style["size"]
            if "thickness" in style:
                inputs["ClickThickness"] = style["thickness"]
            if "color" in style:
                value = style["color"].lstrip("#")
                inputs.update(TopLeftRed=int(value[:2], 16) / 255, TopLeftGreen=int(value[2:4], 16) / 255, TopLeftBlue=int(value[4:6], 16) / 255)
            self.title("Click", "Clicks", start + c, start + min(c + self.scaled(30), limit), "Click", {"Ripple": inputs})
        chip = scene.get("chip")
        if chip:
            a, b = max(self.frames(chip["from"]), head), min(self.frames(chip["to"]), end_local)
            transform = split_channels(self.keys_for(tip_at, moves, a, b), tip_at(a))
            self.plan["clips"].append({"track": "Chip", "file": self.chip_asset(chip), "size": [W, H], "start": start + a, "in": a, "out": b,
                                       "transform": transform, "fades": [self.scaled(15), self.scaled(12)]})

    def chip_asset(self, chip):
        ss = 4
        if not self.bold:
            raise SystemExit(f'a chip needs a font file, and none was found for {self.brand["font"]} {self.brand["styles"]["bold"]}. Set "fontFile" in the brand to the bold file.')
        bold = ImageFont.truetype(self.bold, 30 * ss)
        icon = chip.get("icon", "")
        symbol_file = os.path.join(os.environ.get("WINDIR", ""), "Fonts", "seguisym.ttf")
        symbol = ImageFont.truetype(symbol_file, 30 * ss) if icon and os.path.exists(symbol_file) else bold
        icon_text = icon + " " if icon else ""
        icon_w = symbol.getlength(icon_text) if icon else 0
        chip_w = int(icon_w + bold.getlength(chip["text"]) + 48 * ss)
        chip_h = int(64 * ss)
        art = Image.new("RGBA", (chip_w + 4 * ss, chip_h + 4 * ss), (0, 0, 0, 0))
        draw = ImageDraw.Draw(art)
        colors = self.brand["colors"]
        draw.rounded_rectangle((0, 0, chip_w, chip_h), radius=12 * ss, fill=colors["chip"], outline=colors["accent"], width=2 * ss)
        if icon:
            draw.text((24 * ss, chip_h / 2), icon_text, font=symbol, fill="white", anchor="lm")
        draw.text((24 * ss + icon_w, chip_h / 2), chip["text"], font=bold, fill="white", anchor="lm")
        small = art.resize((art.width // ss, art.height // ss), Image.LANCZOS)
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        frame.paste(small, (W // 2 + 22, H // 2 + 28))
        name = "chip-" + re.sub(r"\W+", "-", chip["text"]).strip("-").lower() + ".png"
        path = os.path.join(self.assets, name)
        frame.save(path)
        return path

    def cursor_asset(self):
        """A cursor with the point it clicks at in the middle of the frame, so Position is where it points."""
        ss = 4
        unit = 52 / 24 * ss
        points, x, y = [], 4.0, 2.0
        points.append((x, y))
        for dx, dy in [(15, 11.5), (-6.6, 1), (3.9, 7.2), (-3, 1.6), (-3.8, -7.3)]:
            x, y = x + dx, y + dy
            points.append((x, y))
        points.append((4.8, 20))
        ox, oy = W / 2 * ss - 8 * ss, H / 2 * ss - 4 * ss
        scaled = [(ox + px * unit, oy + py * unit) for px, py in points]
        box = (W // 2 - 60, H // 2 - 40, W // 2 + 100, H // 2 + 100)
        size = ((box[2] - box[0]) * ss, (box[3] - box[1]) * ss)
        local = [(px - box[0] * ss, py - box[1] * ss) for px, py in scaled]
        art = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(art)
        draw.polygon(local, fill=(255, 255, 255, 255))
        draw.line(local + local[:2], fill=(0x10, 0x16, 0x1f, 255), width=int(round(1.4 * unit)), joint="curve")
        shadow = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).polygon([(px, py + 3 * ss) for px, py in local], fill=(0, 0, 0, 153))
        shadow = shadow.filter(ImageFilter.GaussianBlur(5 * ss / 2))
        shadow.alpha_composite(art)
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        frame.paste(shadow.resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS), box[:2])
        frame.save(os.path.join(self.assets, "cursor.png"))

    def tracks(self):
        rows = []
        for stem in LAYER_ORDER:
            if stem == "Overlay":
                rows += [f"Overlay {i + 1}" for i in range(len(self.overlay_tracks))]
            elif stem == "Labels":
                rows += [f"Labels {i + 1}" for i in range(len(self.label_tracks))]
            elif stem == "Highlights":
                rows += [f"Highlights {i + 1}" for i in range(len(self.highlight_tracks))]
            else:
                rows.append(stem)
        return rows

    def check_overlaps(self):
        rows = {}
        for item in self.plan["clips"]:
            rows.setdefault(item["track"], []).append((item["start"], item["start"] + item["out"] - item["in"], os.path.basename(item["file"])))
        for item in self.plan["titles"]:
            rows.setdefault(item["track"], []).append((item["start"], item["end"], item["name"]))
        for track, items in rows.items():
            items.sort()
            for a, b in zip(items, items[1:]):
                if b[0] < a[1]:
                    raise SystemExit(f"{track}: {a[2]} ({a[0] / self.fps:.2f}-{a[1] / self.fps:.2f} s) overlaps {b[2]} ({b[0] / self.fps:.2f}-{b[1] / self.fps:.2f} s). Change the times in film.json.")

    def build(self):
        os.makedirs(self.assets, exist_ok=True)
        self.cursor_asset()
        scenes = self.film["scenes"]
        start = 0
        for i, scene in enumerate(scenes):
            dur = self.frames(scene["seconds"])
            head = self.half if i > 0 else 0
            tail = self.half if i + 1 < len(scenes) else 0
            if i > 0 and self.transition:
                self.plan["cuts"].append(start + head)
            self.plan["markers"].append({"frame": start + head, "name": scene.get("name") or scene.get("headline") or f"Scene {i + 1}"})
            self.scene_starts.append((self.plan["markers"][-1]["name"], start / self.fps))
            self.scene(scene, start, head, tail, dur)
            start += dur - self.transition
        self.plan["total"] = start + self.transition
        if not self.plan["clips"]:
            raise SystemExit("the film has no clips. A timeline of cards alone can't be built this way: add a screen or a backdrop scene.")
        self.plan["tracks"] = self.tracks()
        self.check_overlaps()
        return self.plan


def path_url(path):
    return "file://localhost/" + quote(path.replace("\\", "/").lstrip("/"), safe="/:")


def write_xml(plan):
    """One track per planned track that has clips. patch_drt.py sorts them onto the planned tracks by start and name."""
    fps = plan["fps"]
    rate = f"<rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>"
    file_ids = {}
    tracks = []
    for track in plan["tracks"]:
        clips = sorted((c for c in plan["clips"] if c["track"] == track), key=lambda c: c["start"])
        if not clips:
            continue
        rows = []
        for c in clips:
            name = os.path.basename(c["file"])
            if c["file"] in file_ids:
                file_xml = f'<file id="{file_ids[c["file"]]}"/>'
            else:
                file_ids[c["file"]] = f"f{len(file_ids) + 1}"
                file_xml = (f'<file id="{file_ids[c["file"]]}"><name>{escape(name)}</name><pathurl>{escape(path_url(c["file"]))}</pathurl>'
                            f'{rate}<duration>1</duration>'
                            f'<media><video><samplecharacteristics><width>{c["size"][0]}</width><height>{c["size"][1]}</height></samplecharacteristics></video></media></file>')
            length = c["out"] - c["in"]
            rows.append(
                f'<clipitem id="c{len(rows)}_{track.replace(" ", "")}"><name>{escape(name)}</name><duration>{length}</duration>{rate}'
                f'<start>{c["start"]}</start><end>{c["start"] + length}</end><in>{c["in"]}</in><out>{c["out"]}</out>{file_xml}'
                f'<filter><effect><name>Basic Motion</name><effectid>basic</effectid><effectcategory>motion</effectcategory><effecttype>motion</effecttype><mediatype>video</mediatype>'
                f'<parameter authoringApp="PremierePro"><parameterid>scale</parameterid><name>Scale</name><valuemin>0</valuemin><valuemax>1000</valuemax><value>100</value></parameter>'
                f'</effect></filter></clipitem>'
            )
        tracks.append("<track>" + "".join(rows) + "</track>")
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="5"><sequence><name>{escape(plan["name"])}</name><duration>{plan["total"]}</duration>'
        f'{rate}<in>-1</in><out>-1</out>'
        f'<timecode><string>01:00:00:00</string><frame>{plan["base"]}</frame><displayformat>NDF</displayformat>{rate}</timecode>'
        f'<media><video><format><samplecharacteristics><width>{W}</width><height>{H}</height><pixelaspectratio>square</pixelaspectratio>'
        f'{rate}</samplecharacteristics></format>' + "".join(tracks) + "</video></media></sequence></xmeml>\n"
    )


def main(work):
    work = os.path.abspath(work)
    film = load_film(work)
    planner = Planner(work, film)
    plan = planner.build()
    build = os.path.join(work, "build")
    with open(os.path.join(build, "film.xml"), "w", encoding="utf8") as f:
        f.write(write_xml(plan))
    with open(os.path.join(build, "plan.json"), "w", encoding="utf8") as f:
        json.dump(plan, f, indent=1)
    print(f'{plan["name"]}: {plan["total"] / plan["fps"]:.2f} s, {plan["total"]} frames at {plan["fps"]} fps, {len(plan["clips"])} clips, {len(plan["titles"])} titles')
    print("tracks:", ", ".join(t for t in plan["tracks"] if any(i["track"] == t for i in plan["clips"] + plan["titles"])))
    print("scene starts (timeline time = this + the scene's own time):")
    for name, seconds in planner.scene_starts:
        print(f"  {seconds:7.2f} s  {name}")
    for warning in planner.warnings:
        print("WARNING:", warning)


if __name__ == "__main__":
    main(sys.argv[1])
