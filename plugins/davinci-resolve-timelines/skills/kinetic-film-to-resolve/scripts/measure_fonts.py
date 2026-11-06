# measure_fonts.py <film folder> <font name> <style>: measures each word's width in the chosen font and writes
# <film>/resolve/em.json, so words fill the frame exactly. Needs Pillow (pip install pillow), outside Resolve.
import json, os, re, sys
from PIL import ImageFont

film, name, style = sys.argv[1], sys.argv[2], sys.argv[3]
dirs = [os.path.expandvars(r'%WINDIR%\Fonts'), os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\Windows\Fonts'), '/Library/Fonts', os.path.expanduser('~/Library/Fonts'), '/System/Library/Fonts', '/usr/share/fonts', os.path.expanduser('~/.fonts')]
norm = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
want, wstyle = norm(name), norm(style)
candidates = []
for d in dirs:
    for root, _, files in os.walk(d):
        for f in files:
            if f.lower().endswith(('.ttf', '.otf')) and norm(f).startswith(want):
                candidates.append(os.path.join(root, f))
exact = [c for c in candidates if norm(os.path.splitext(os.path.basename(c))[0]) == want + wstyle]
variable = [c for c in candidates if 'wght' in c.lower() or '[' in c]
pick = (exact or [c for c in candidates if wstyle in norm(os.path.basename(c))] or variable or candidates or [None])[0]
if not pick:
    print(json.dumps({'error': 'no font file found for %s %s; words will use estimated widths' % (name, style)})); sys.exit(0)
font = ImageFont.truetype(pick, 1000)
words = json.load(open(os.path.join(film, 'resolve', 'words.json'), encoding='utf-8'))
ems = {}
for w in words:
    box = font.getbbox(w)
    ems[w] = round((box[2] - box[0]) / 1000.0, 3)
json.dump(ems, open(os.path.join(film, 'resolve', 'em.json'), 'w', encoding='utf-8'), indent=0)
print(json.dumps({'font_file': pick, 'exact_style': bool(exact), 'words': len(ems)}))
