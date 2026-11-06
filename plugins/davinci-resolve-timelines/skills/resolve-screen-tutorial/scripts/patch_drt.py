"""Turns Resolve's export of the imported clips (build/raw.drt) into the finished timeline file (build/final.drt).

    python patch_drt.py <work>

Each clip gets its Inspector keyframes. The Fusion titles, cloned from build/blueprint.drt, go on at their exact frames and lengths.
The Resolve API can do neither. references/how-it-works.md has the format, as read from exports by Resolve 21.1.1.
"""
import html
import json
import os
import re
import struct
import sys
import uuid
import zipfile
import zlib
from xml.sax.saxutils import escape

try:
    from compression import zstd  # Python 3.14, which is what Resolve's scripting host runs

    def unpack(data):
        return zstd.decompress(data)

    def pack(data):
        return zstd.compress(data, level=3)
except ImportError:
    import zstandard

    def unpack(data):
        return zstandard.ZstdDecompressor().decompress(data, max_output_size=4_000_000)

    def pack(data):
        return zstandard.ZstdCompressor(level=3, write_content_size=True).compress(data)

TRANSFORM_FILTER = 4
PARAMS = {"zoom": [42, 43], "pan": [40], "tilt": [41]}
PARAM_SLOT = {42: 0, 43: 1, 40: 3, 41: 4}
CLIP = r"<Element>\s*<Sm2TiVideoClip DbId=.*?</Sm2TiVideoClip>\s*</Element>"


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def read_varint(buf, i):
    shift = n = 0
    while True:
        b = buf[i]
        i += 1
        n |= (b & 0x7f) << shift
        shift += 7
        if not b & 0x80:
            return n, i


def fields(buf):
    i, out = 0, []
    while i < len(buf):
        tag, i = read_varint(buf, i)
        wire = tag & 7
        if wire == 0:
            value, i = read_varint(buf, i)
        elif wire == 2:
            size, i = read_varint(buf, i)
            value = bytes(buf[i:i + size])
            i += size
        elif wire == 1:
            value = bytes(buf[i:i + 8])
            i += 8
        elif wire == 5:
            value = bytes(buf[i:i + 4])
            i += 4
        else:
            raise ValueError(f"wire type {wire}: this Resolve version may store clips differently than 21.1.1")
        out.append((tag >> 3, wire, value))
    return out


def encode(rows):
    out = bytearray()
    for number, wire, value in rows:
        out += varint(number << 3 | wire)
        if wire == 0:
            out += varint(value)
        elif wire == 2:
            out += varint(len(value)) + value
        else:
            out += value
    return bytes(out)


def key_blob(channel):
    body = b""
    for k in channel["keys"]:
        has_handles = "in" in k or "out" in k
        body += struct.pack("<ihH", int(k["t"]), 0, 0x0d if has_handles else 0x0c) + struct.pack("<d", k["v"])
        if has_handles:
            body += struct.pack("<6d", k.get("in", 0.0), 0.0, k.get("out", 0.0), 0.0, 0.0, 0.0)
    return struct.pack(">i", -len(body)) + body


def param_bytes(number, channel):
    inner = encode([(2, 1, struct.pack("<d", channel["static"]))])
    return encode([(1, 0, number), (3, 2, encode([(1, 2, inner)])), (10, 2, key_blob(channel))])


def transform_rows(rows, transform):
    """The Transform filter lists its parameters by position, and an unset one is an empty field 9."""
    params = [row for row in rows if row[0] == 9]
    rest = [row for row in rows if row[0] != 9]
    values = [row[2] for row in params]
    for name, numbers in PARAMS.items():
        if not transform.get(name, {}).get("keys"):
            continue
        for number in numbers:
            values[PARAM_SLOT[number]] = param_bytes(number, transform[name])
    return rest + [(9, 2, v) for v in values]


def set_transform(blob_hex, transform):
    raw = bytes.fromhex(blob_hex)
    data = raw[9:] if raw[8] == 0x80 else unpack(raw[9:])
    new_top = []
    placed = False
    for number, wire, value in fields(data):
        if number == 1 and wire == 2:
            rows = fields(value)
            if rows and rows[0][:2] == (1, 0) and rows[0][2] == TRANSFORM_FILTER:
                value = encode(transform_rows(rows, transform))
                placed = True
        new_top.append((number, wire, value))
    if not placed:
        raise ValueError("clip has no Transform filter: this Resolve version may store clips differently than 21.1.1")
    data = encode(new_top)
    compressed = pack(data)
    payload = b"\x81" + compressed if len(compressed) < len(data) else b"\x80" + data
    return (raw[:4] + struct.pack(">I", len(payload)) + payload).hex()


def fresh_ids(xml):
    return re.sub(r'DbId="[^"]+"', lambda _: f'DbId="{uuid.uuid4()}"', xml)


def title_blueprints(path):
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.startswith("SeqContainer"))
        xml = z.read(name).decode("utf8")
    out = {}
    for m in re.finditer(CLIP, xml, re.S):
        element = m.group(0)
        if "<PrettyType>Fusion Title</PrettyType>" not in element:
            continue
        composition = re.search(r"<CompositionBA>([0-9a-f]+)", element)
        if not composition:
            raise SystemExit("a blueprint title has no comp: make_blueprint has to open each title's comp before exporting")
        raw = zlib.decompress(bytes.fromhex(composition.group(1))[4:])
        found = re.search(rb'TEMPLATE_ID = "([^"]+)"', raw)
        if found:
            out[found.group(1).decode().rsplit("/", 1)[-1]] = element
    return out


def place(element, start, length, label):
    element = fresh_ids(element)
    element = re.sub(r"<Start>\d+</Start>", f"<Start>{start}</Start>", element, count=1)
    element = re.sub(r"<Duration>\d+</Duration>", f"<Duration>{length}</Duration>", element, count=1)
    return re.sub(r"<Name>[^<]*</Name>", lambda _: f"<Name>{escape(label)}</Name>", element, count=1)


def main(work):
    build = os.path.join(os.path.abspath(work), "build")
    with open(os.path.join(build, "plan.json"), encoding="utf8") as f:
        plan = json.load(f)
    base = plan["base"]
    blueprints = title_blueprints(os.path.join(build, "blueprint.drt"))
    missing = {t["template"] for t in plan["titles"]} - set(blueprints)
    if missing:
        raise SystemExit(f"blueprint has no {sorted(missing)}, only {sorted(blueprints)}. Are the templates installed, and was Resolve able to see them?")

    src = zipfile.ZipFile(os.path.join(build, "raw.drt"))
    seq_name = next(n for n in src.namelist() if n.startswith("SeqContainer"))
    xml = src.read(seq_name).decode("utf8")

    # Every clip Resolve imported, by the frame it starts on and the file it shows.
    planned = {(base + c["start"], os.path.basename(c["file"])): c for c in plan["clips"]}
    by_track = {name: [] for name in plan["tracks"]}
    seen = 0
    for m in re.finditer(CLIP, xml, re.S):
        element = m.group(0)
        start = int(re.search(r"<Start>(\d+)</Start>", element).group(1))
        name = html.unescape(re.search(r"<Name>([^<]*)</Name>", element).group(1))
        clip = planned.get((start, name))
        if clip is None:
            raise SystemExit(f"Resolve imported {name} at frame {start}, which isn't in the plan. Does the timeline's frame rate match the film's?")
        blob = re.search(r"<EffectFiltersBA>([0-9a-f]*)</EffectFiltersBA>", element)
        if not blob or not blob.group(1):
            raise SystemExit(f"{name} at {start} has no Inspector data")
        element = element.replace(blob.group(0), f'<EffectFiltersBA>{set_transform(blob.group(1), clip["transform"])}</EffectFiltersBA>')
        by_track[clip["track"]].append((start, element))
        seen += 1
    if seen != len(plan["clips"]):
        raise SystemExit(f"Resolve imported {seen} clips, the plan has {len(plan['clips'])}")

    for t in plan["titles"]:
        start = base + t["start"]
        by_track[t["track"]].append((start, place(blueprints[t["template"]], start, t["end"] - t["start"], t["name"])))

    track_xml = re.search(r"<VideoTrackVec>\s*(<Element>\s*<Sm2TiTrack .*?</Sm2TiTrack>\s*</Element>)", xml, re.S).group(1)
    used = [name for name in plan["tracks"] if by_track[name]]
    tracks = []
    for name in used:
        items = "".join(e for _, e in sorted(by_track[name], key=lambda row: row[0]))
        one = re.sub(r"<Items>.*</Items>", lambda _: "<Items>" + items + "</Items>", track_xml, flags=re.S)
        one = re.sub(r'<Sm2TiTrack DbId="[^"]+"', f'<Sm2TiTrack DbId="{uuid.uuid4()}"', one, count=1)
        tracks.append(one)
    xml = re.sub(r"<VideoTrackVec>.*</VideoTrackVec>", lambda _: "<VideoTrackVec>" + "".join(tracks) + "</VideoTrackVec>", xml, flags=re.S)

    with zipfile.ZipFile(os.path.join(build, "final.drt"), "w", zipfile.ZIP_DEFLATED) as out:
        for n in src.namelist():
            out.writestr(n, xml.encode("utf8") if n == seq_name else src.read(n))
    print("tracks", used, "clips", seen, "titles", len(plan["titles"]))


if __name__ == "__main__":
    main(sys.argv[1])
