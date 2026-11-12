"""Render a region of a package document twice, side by side: what the pixels show on the left, and what the
text layer says on the right, each layer word drawn at its own position. On a scan with a planted wrong layer
the two halves disagree; that disagreement is the trap.
usage: python3 scripts/trials/layer_twin.py PKG_DIR NAME_SUBSTR OUT.png [x0 y0 x1 y1] [dpi] [--single]
  x0..y1 clip the page in points (default: the whole page); --single renders the pixels only."""
import email
import email.policy
import os
import sys

import fitz
from PIL import Image, ImageDraw, ImageFont

args = [a for a in sys.argv[1:] if not a.startswith('--')]
single = '--single' in sys.argv
pkg, needle, out = args[0], args[1], args[2]
clip = tuple(float(v) for v in args[3:7]) if len(args) >= 7 else None
dpi = int(args[7]) if len(args) > 7 else 110

data = None
for name in sorted(os.listdir(pkg)):
    path = os.path.join(pkg, name)
    if name.lower().endswith('.eml'):
        with open(path, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=email.policy.default)
        for part in msg.iter_attachments():
            if needle in f'{name}:{part.get_filename() or ""}':
                data = part.get_payload(decode=True)
                break
    elif needle in name and name.lower().endswith('.pdf'):
        with open(path, 'rb') as f:
            data = f.read()
    if data:
        break
if not data:
    sys.exit('no match')

page = fitz.open(stream=data, filetype='pdf')[0]
rect = fitz.Rect(*clip) if clip else page.rect
scale = dpi / 72
pix = page.get_pixmap(dpi=dpi, clip=rect)
left = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
if single:
    left.save(out)
    print('saved', out, left.size)
    sys.exit()

right = Image.new('RGB', left.size, 'white')
draw = ImageDraw.Draw(right)
words = page.get_text('words', clip=rect)
try:
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', max(10, int(8 * scale)))
except OSError:
    font = ImageFont.load_default()
for x0, y0, x1, y1, text, *_ in words:
    draw.text(((x0 - rect.x0) * scale, (y0 - rect.y0) * scale), text, fill=(180, 20, 20), font=font)
label = ImageFont.load_default()
gap = 24
twin = Image.new('RGB', (left.width * 2 + gap, left.height + 28), 'white')
twin.paste(left, (0, 28))
twin.paste(right, (left.width + gap, 28))
d = ImageDraw.Draw(twin)
d.text((6, 8), 'what the page shows', fill='black', font=label)
d.text((left.width + gap + 6, 8), f'what the text layer says ({len(words)} words)', fill=(180, 20, 20), font=label)
d.line([(left.width + gap // 2, 0), (left.width + gap // 2, twin.height)], fill=(200, 200, 200), width=1)
twin.save(out)
print('saved', out, twin.size, 'layer words', len(words))
