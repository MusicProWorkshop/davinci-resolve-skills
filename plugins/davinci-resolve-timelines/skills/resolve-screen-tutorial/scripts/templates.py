"""Writes a brand's four Fusion titles, and with --install puts them in Resolve's Templates folder.

    python templates.py <work> [--install | --uninstall]

<prefix> Caption    caption bar with a label or a step number
<prefix> Card       title and end cards
<prefix> Highlight  ring around a button or element
<prefix> Click      click ripple

Times in the expressions are frames at the film's frame rate. Sizes are pixels on a 1920x1080 frame.
"""
import os
import re
import sys

from plan import load_film

FONT_PX = 1249.0  # Text+ Size 1 is a font this many pixels tall on a 1920-wide frame.


def install_dir(folder):
    if sys.platform == "win32":
        base = os.path.join(os.environ["APPDATA"], "Blackmagic Design", "DaVinci Resolve", "Support", "Fusion")
    else:
        base = os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion")
    return os.path.join(base, "Templates", "Edit", "Titles", folder)


def rgb(hex_color):
    c = hex_color.lstrip("#")
    return [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def inp(name, value=None, expr=None, source=None):
    if source:
        # A mask's output is named Mask, not Output. Wired to Output, the masked solid floods the frame.
        output = "Mask" if name == "EffectMask" else "Output"
        return f'{name} = Input {{ SourceOp = {q(source)}, Source = {q(output)}, }},'
    if expr is not None:
        return f'{name} = Input {{ Expression = {q(expr)}, }},'
    if isinstance(value, str):
        return f'{name} = Input {{ Value = {q(value)}, }},'
    return f'{name} = Input {{ Value = {value}, }},'


def tool(name, kind, inputs, extra=""):
    body = "\n".join("\t\t\t\t\t\t" + line for line in inputs)
    return f'\t\t\t\t{name} = {kind} {{\n\t\t\t\t\tInputs = {{\n{body}\n\t\t\t\t\t}},\n{extra}\t\t\t\t}},'


def background(name, color, alpha=1.0, mask=None, color_expr=None):
    r, g, b = rgb(color) if color else (0, 0, 0)
    rows = [inp("UseFrameFormatSettings", 1)]
    if color_expr:
        rows += [inp("TopLeftRed", expr=color_expr[0]), inp("TopLeftGreen", expr=color_expr[1]), inp("TopLeftBlue", expr=color_expr[2])]
    else:
        rows += [inp("TopLeftRed", r * alpha), inp("TopLeftGreen", g * alpha), inp("TopLeftBlue", b * alpha)]
    rows.append(inp("TopLeftAlpha", alpha))
    if mask:
        rows.append(inp("EffectMask", source=mask))
    return lambda extra="": tool(name, "Background", rows, extra)


def rect_mask(name, cx, cy, w, h, radius=None, solid=True, border=None):
    rows = [inp("UseFrameFormatSettings", 1), inp("Center", expr=f"Point({cx}, {cy})"), inp("Width", expr=w), inp("Height", expr=h)]
    if radius is not None:
        rows.append(inp("CornerRadius", expr=radius))
    if not solid:
        rows.append(inp("Solid", 0))
    if border is not None:
        rows.append(inp("BorderWidth", expr=border))
    return tool(name, "RectangleMask", rows)


def text(name, size_px, font, style, color, styled=None, styled_expr=None, center_expr=None, size_expr=None):
    rows = [inp("UseFrameFormatSettings", 1), inp("Font", font), inp("Style", style)]
    rows.append(inp("Size", expr=size_expr) if size_expr else inp("Size", size_px / FONT_PX))
    if styled_expr:
        rows.append(inp("StyledText", expr=styled_expr))
    else:
        rows.append(inp("StyledText", styled or ""))
    if center_expr:
        rows.append(inp("Center", expr=center_expr))
    r, g, b = rgb(color)
    rows += [inp("Red1", r), inp("Green1", g), inp("Blue1", b)]
    return tool(name, "TextPlus", rows)


def placed(name, source, center_expr):
    """A Text+ cannot read its own measured size in its own Center, so a Transform after it does the placing."""
    return tool(name, "Transform", [inp("Input", source=source), inp("Center", expr=center_expr)])


def merge(name, back, fore, blend_expr=None):
    rows = [inp("Background", source=back), inp("Foreground", source=fore), inp("PerformDepthMerge", 0)]
    if blend_expr:
        rows.append(inp("Blend", expr=blend_expr))
    return tool(name, "Merge", rows)


def number_control(name, label, default, lo, hi, integer=False):
    integer_line = "INP_Integer = true, " if integer else ""
    return (f'{name} = {{ LINKS_Name = {q(label)}, LINKID_DataType = "Number", INPID_InputControl = "SliderControl", '
            f'{integer_line}INP_Default = {default}, INP_MinScale = {lo}, INP_MaxScale = {hi}, ICS_ControlPage = "Controls", }},')


def combo_control(name, label, options):
    rows = "".join(f'{{ CCS_AddString = {q(o)}, }}, ' for o in options)
    return (f'{name} = {{ LINKS_Name = {q(label)}, LINKID_DataType = "Number", INPID_InputControl = "ComboControl", '
            f'INP_Integer = true, INP_Default = 0, ICS_ControlPage = "Controls", CC_LabelPosition = "Horizontal", {rows}}},')


def checkbox_control(name, label, default):
    return (f'{name} = {{ LINKS_Name = {q(label)}, LINKID_DataType = "Number", INPID_InputControl = "CheckboxControl", '
            f'INP_Integer = true, INP_Default = {default}, ICS_ControlPage = "Controls", CBC_TriState = false, }},')


def user_controls(rows):
    body = "\n".join("\t\t\t\t\t\t" + row for row in rows)
    return f'\t\t\t\t\tUserControls = ordered() {{\n{body}\n\t\t\t\t\t}},\n'


def macro(name, published, output, tools):
    rows = []
    for i, (source_op, source, label, default) in enumerate(published, 1):
        default_part = "" if default is None else f" Default = {default},"
        rows.append(f'\t\t\t\tInput{i} = InstanceInput {{ SourceOp = {q(source_op)}, Source = {q(source)}, Name = {q(label)},{default_part} }},')
    inputs = "\n".join(rows)
    body = "\n".join(tools)
    op = re.sub(r"\W", "_", name)
    return (f'{{\n\tTools = ordered() {{\n\t\t{op} = MacroOperator {{\n\t\t\tCtrlWZoom = false,\n\t\t\tInputs = ordered() {{\n{inputs}\n\t\t\t}},\n'
            f'\t\t\tOutputs = {{\n\t\t\t\tMainOutput1 = InstanceOutput {{ SourceOp = {q(output)}, Source = "Output", }},\n\t\t\t}},\n'
            f'\t\t\tViewInfo = GroupInfo {{ Pos = {{ 0, 0 }}, }},\n\t\t\tTools = ordered() {{\n{body}\n\t\t\t}},\n\t\t}},\n\t}},\n}}\n')


class Templates:
    def __init__(self, film):
        self.brand = film["brand"]
        self.scale = int(film["fps"]) / 60
        self.prefix = self.brand["prefix"]
        self.font = self.brand["font"]
        self.styles = self.brand["styles"]
        self.colors = self.brand["colors"]

    def f(self, frames_at_60):
        """Animation lengths were tuned at 60 fps."""
        return round(frames_at_60 * self.scale, 3)

    def caption(self):
        c = self.colors
        roles = self.brand["labels"]
        step = len(roles) + 1
        label = "Pill.Label"
        has_bar = "(Pill.ShowBar == 1)"
        text_w = f"iif({has_bar}, TextMain.Output.DataWindow[3] - TextMain.Output.DataWindow[1], 0)"
        badge_w = f"iif({label} == 0, 0, iif({label} == {step}, 68, BadgeText.Output.DataWindow[3] - BadgeText.Output.DataWindow[1] + 52))"
        left_pad = f"iif({has_bar}, iif({label} == 0, 44, 22), 0)"
        right_pad = f"iif({has_bar}, 44, 0)"
        gap = f"iif({has_bar} and {label} ~= 0, 26, 0)"
        bar_w = f"({left_pad} + {badge_w} + {gap} + {text_w} + {right_pad})"
        bar_h = f"iif({label} == 0, 95, iif({label} == {step}, 108, 105))"
        y = f"((56 + {bar_h} / 2) / 1080)"
        text_x = f"(0.5 + ({bar_w} / 2 - {right_pad} - ({text_w}) / 2) / 1920)"
        badge_x = f"(0.5 + (-{bar_w} / 2 + {left_pad} + ({badge_w}) / 2) / 1920)"
        badge_h = f"iif({label} == {step}, 68, 65)"
        ease = f"(1 - (1 - min(time / {self.f(18)}, 1)) ^ 3)"
        badge_text = f'iif({label} == {step}, string.format("%d", Pill.StepNumber), "")'
        for i, row in reversed(list(enumerate(roles, 1))):
            badge_text = f'iif({label} == {i}, {q(row["name"])}, {badge_text})'

        def role_channel(i):
            value = str(rgb(c["accent"])[i])
            for k, row in reversed(list(enumerate(roles, 1))):
                value = f'iif({label} == {k}, {rgb(row["color"])[i]}, {value})'
            return value

        controls = user_controls([
            combo_control("Label", "Label", ["None"] + [row["name"] for row in roles] + ["Step"]),
            number_control("StepNumber", "Step Number", 1, 1, 9, integer=True),
            checkbox_control("ShowBar", "Show Bar", 1),
            number_control("OffsetX", "Offset X", 0, -960, 960),
            number_control("OffsetY", "Offset Y", 0, -1080, 0),
        ])
        pill = background("Pill", c["page"], 0.96, mask="PillMask")
        tools = [
            rect_mask("ShadowMask", 0.5, f"{y} - 12 / 1080", f"{bar_w} / 1920", f"{bar_h} / 1080", radius="1"),
            background("ShadowFill", "#000000", 0.55, mask="ShadowMask")(),
            tool("ShadowBlur", "Blur", [inp("Input", source="ShadowFill"), inp("XBlurSize", 22)]),
            rect_mask("PillMask", 0.5, y, f"{bar_w} / 1920", f"{bar_h} / 1080", radius="1"),
            pill(controls),
            rect_mask("EdgeMask", 0.5, y, f"{bar_w} / 1920", f"{bar_h} / 1080", radius="1", solid=False, border="0.0006"),
            background("Edge", "#ffffff", 0.16, mask="EdgeMask")(),
            merge("WithShadow", "ShadowBlur", "Pill"),
            merge("WithEdge", "WithShadow", "Edge"),
            tool("Clear", "Background", [inp("UseFrameFormatSettings", 1), inp("TopLeftAlpha", 0)]),
            merge("Bar", "Clear", "WithEdge", blend_expr="Pill.ShowBar"),
            rect_mask("BadgeMask", badge_x, y, f"{badge_w} / 1920", f"{badge_h} / 1080", radius="1"),
            background("BadgeFill", None, 1.0, mask="BadgeMask", color_expr=(role_channel(0), role_channel(1), role_channel(2)))(),
            merge("WithBadge", "Bar", "BadgeFill", blend_expr=f"iif({label} == 0, 0, 1)"),
            text("BadgeText", 34, self.font, self.styles["bold"], c["badgeText"], styled_expr=f"Text({badge_text})",
                 size_expr=f"iif({label} == {step}, 40, 34) / {FONT_PX}"),
            placed("BadgeTextAt", "BadgeText", f"Point({badge_x}, {y})"),
            merge("WithBadgeText", "WithBadge", "BadgeTextAt", blend_expr=f"iif({label} == 0, 0, 1)"),
            text("TextMain", 46, self.font, self.styles["bold"], c["text"], styled="Caption"),
            placed("TextMainAt", "TextMain", f"Point({text_x}, {y})"),
            merge("WithText", "WithBadgeText", "TextMainAt", blend_expr="Pill.ShowBar"),
            tool("Rise", "Transform", [inp("Input", source="WithText"), inp(
                "Center", expr=f"Point(0.5 + Pill.OffsetX / 1920, 0.5 - Pill.OffsetY / 1080 - (1 - {ease}) * 20 / 1080)")]),
        ]
        published = [
            ("TextMain", "StyledText", "Text", None),
            ("Pill", "Label", "Label", 0),
            ("Pill", "StepNumber", "Step Number", 1),
            ("Pill", "ShowBar", "Show Bar", 1),
            ("Pill", "OffsetX", "Offset X", 0),
            ("Pill", "OffsetY", "Offset Y", 0),
        ]
        return macro(f"{self.prefix} Caption", published, "Rise", tools)

    def card(self):
        c = self.colors
        bars = self.brand["logoBars"]
        wordmark = self.brand["wordmark"]
        logo_scale = 0.6
        lockup_top = 333.5
        logo_w = (max(b["x"] for b in bars) + 32) * logo_scale if bars else 0
        gap = 30 if bars and wordmark else 0
        word_w = "(Wordmark.Output.DataWindow[3] - Wordmark.Output.DataWindow[1])" if wordmark else "0"
        left = f"(960 - ({logo_w} + {gap} + {word_w}) / 2)"
        bar_bottom = lockup_top + (max(b["h"] for b in bars) + 8) * logo_scale if bars else 0
        tools = [background("Ground", c["page"])()]
        last = "Ground"
        grow_len, rise_len = self.f(36), self.f(36)
        for i, b in enumerate(bars):
            grow = f"(1 - 2 ^ (-10 * max(0, min((time - {self.f(i * 4)}) / {grow_len}, 1))))"
            px = f"({b['h'] * logo_scale} * {grow})"
            cx = f"(({left} + {b['x'] * logo_scale + 16 * logo_scale}) / 1920)"
            cy = f"(1 - ({bar_bottom} - {px} / 2) / 1080)"
            tools.append(rect_mask(f"BarMask{i}", cx, cy, f"{32 * logo_scale} / 1920", f"{px} / 1080", radius="0.5"))
            tools.append(background(f"BarFill{i}", b.get("color") or c["logo"], mask=f"BarMask{i}")())
            tools.append(merge(f"WithBar{i}", last, f"BarFill{i}"))
            last = f"WithBar{i}"
        rise = lambda delay: f"(28 * 2 ^ (-10 * max(0, min((time - {self.f(delay)}) / {rise_len}, 1))))"
        fade = lambda delay: f"max(0, min((time - {self.f(delay)}) / {self.f(30)}, 1))"
        if wordmark:
            word_opacity = f"max(0, min((time - {self.f(9)}) / {self.f(27)}, 1))"
            word_x = f"(({left} + {logo_w} + {gap} + {word_w} / 2) / 1920)"
            tools += [
                text("Wordmark", 76, self.brand.get("wordmarkFont") or self.font, self.brand.get("wordmarkStyle") or self.styles["black"], c["logo"], styled=wordmark),
                placed("WordmarkAt", "Wordmark", f"Point({word_x}, {1 - (lockup_top + 48) / 1080})"),
                merge("WithWord", last, "WordmarkAt", blend_expr=word_opacity),
            ]
            last = "WithWord"
        tools += [
            text("Headline", 132, self.font, self.styles["bold"], c["text"], styled="Headline", center_expr=f"Point(0.5, {1 - 580 / 1080} - {rise(18)} / 1080)"),
            merge("WithHeadline", last, "Headline", blend_expr=fade(18)),
            text("Line", 56, self.font, self.styles["regular"], c["subtle"], styled="Line", center_expr=f"Point(0.5, {1 - 713 / 1080} - {rise(30)} / 1080)"),
            merge("WithLine", "WithHeadline", "Line", blend_expr=fade(30)),
        ]
        published = [("Headline", "StyledText", "Headline", None), ("Line", "StyledText", "Line", None)]
        return macro(f"{self.prefix} Card", published, "WithLine", tools)

    def highlight(self):
        accent = rgb(self.colors["accent"])
        controls = user_controls([
            number_control("RingX", "X", 760, 0, 1920),
            number_control("RingY", "Y", 440, 0, 1080),
            number_control("RingWidth", "Width", 400, 1, 1920),
            number_control("RingHeight", "Height", 200, 1, 1080),
            number_control("RingThickness", "Thickness", 3, 1, 20),
            number_control("RingRadius", "Corner Radius", 10, 0, 100),
            number_control("RingGlow", "Glow", 22, 0, 100),
        ])
        cx = "((Ring.RingX + Ring.RingWidth / 2) / 1920)"
        cy = "(1 - (Ring.RingY + Ring.RingHeight / 2) / 1080)"
        radius = "(2 * Ring.RingRadius / min(Ring.RingWidth, Ring.RingHeight))"
        rows = [inp("UseFrameFormatSettings", 1), inp("TopLeftRed", accent[0]), inp("TopLeftGreen", accent[1]), inp("TopLeftBlue", accent[2]),
                inp("TopLeftAlpha", 1), inp("EffectMask", source="RingMask")]
        tools = [
            rect_mask("RingMask", cx, cy, "Ring.RingWidth / 1920", "Ring.RingHeight / 1080", radius=radius, solid=False, border="Ring.RingThickness / 1920"),
            tool("Ring", "Background", rows, controls),
            tool("GlowBlur", "Blur", [inp("Input", source="Ring"), inp("XBlurSize", expr="Ring.RingGlow / 2")]),
            merge("Glow2", "GlowBlur", "GlowBlur"),
            merge("WithRing", "Glow2", "Ring"),
        ]
        published = [("Ring", name, label, default) for name, label, default in [
            ("RingX", "X", 760), ("RingY", "Y", 440), ("RingWidth", "Width", 400), ("RingHeight", "Height", 200),
            ("RingThickness", "Thickness", 3), ("RingRadius", "Corner Radius", 10), ("RingGlow", "Glow", 22)]]
        published += [("Ring", "TopLeftRed", "Red", accent[0]), ("Ring", "TopLeftGreen", "Green", accent[1]), ("Ring", "TopLeftBlue", "Blue", accent[2])]
        return macro(f"{self.prefix} Highlight", published, "WithRing", tools)

    def click(self):
        accent = rgb(self.colors["accent"])
        controls = user_controls([
            number_control("ClickX", "X", 960, 0, 1920),
            number_control("ClickY", "Y", 540, 0, 1080),
            number_control("ClickSize", "Size", 140, 10, 400),
            number_control("ClickThickness", "Thickness", 7, 1, 30),
        ])
        u = f"min(time / {self.f(30)}, 1)"
        px = f"(Ripple.ClickSize * (0.2 + 0.8 * {u}))"
        rows = [inp("UseFrameFormatSettings", 1), inp("TopLeftRed", accent[0]), inp("TopLeftGreen", accent[1]), inp("TopLeftBlue", accent[2]),
                inp("TopLeftAlpha", 1), inp("EffectMask", source="RippleMask")]
        tools = [
            # An EllipseMask's Height is relative to the frame's width, unlike a RectangleMask's.
            tool("RippleMask", "EllipseMask", [inp("UseFrameFormatSettings", 1), inp("Center", expr="Point(Ripple.ClickX / 1920, 1 - Ripple.ClickY / 1080)"),
                                               inp("Width", expr=f"{px} / 1920"), inp("Height", expr=f"{px} / 1920"), inp("Solid", 0), inp("BorderWidth", expr=f"Ripple.ClickThickness * (0.2 + 0.8 * {u}) / 1920")]),
            tool("Ripple", "Background", rows, controls),
            tool("Clear", "Background", [inp("UseFrameFormatSettings", 1), inp("TopLeftAlpha", 0)]),
            merge("Fading", "Clear", "Ripple", blend_expr=f"1 - {u}"),
        ]
        published = [("Ripple", "ClickX", "X", 960), ("Ripple", "ClickY", "Y", 540), ("Ripple", "ClickSize", "Size", 140), ("Ripple", "ClickThickness", "Thickness", 7),
                     ("Ripple", "TopLeftRed", "Red", accent[0]), ("Ripple", "TopLeftGreen", "Green", accent[1]), ("Ripple", "TopLeftBlue", "Blue", accent[2])]
        return macro(f"{self.prefix} Click", published, "Fading", tools)


def uninstall(film):
    folder = install_dir(film["brand"]["folder"])
    for kind in ("Caption", "Card", "Highlight", "Click"):
        path = os.path.join(folder, f'{film["brand"]["prefix"]} {kind}.setting')
        if os.path.exists(path):
            os.remove(path)
            print("removed", path)
    if os.path.isdir(folder) and not os.listdir(folder):
        os.rmdir(folder)


def main(work, install=False):
    work = os.path.abspath(work)
    film = load_film(work)
    if "--uninstall" in sys.argv:
        uninstall(film)
        return
    made = Templates(film)
    out = os.path.join(work, "build", "templates")
    folders = [out]
    if install:
        folders.append(install_dir(film["brand"]["folder"]))
    for folder in folders:
        os.makedirs(folder, exist_ok=True)
    for kind, make in (("Caption", made.caption), ("Card", made.card), ("Highlight", made.highlight), ("Click", made.click)):
        content = make()
        for folder in folders:
            with open(os.path.join(folder, f'{film["brand"]["prefix"]} {kind}.setting'), "w", encoding="utf8", newline="\n") as f:
                f.write(content)
    print("wrote", out)
    if install:
        print("installed", folders[1])


if __name__ == "__main__":
    main(sys.argv[1], "--install" in sys.argv)
