"""Build the web logo and icons in static/ from the source images in this folder.

Run from the project root after changing logo-source.png or icon-source.png:
    pip install Pillow
    python branding/make_icons.py
"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__)) + '/'
STATIC = os.path.join(HERE, '..', 'static') + '/'
OUT = STATIC + 'img/'
os.makedirs(OUT, exist_ok=True)

# Logo: drop faint alpha noise, crop tight with a small margin, scale for retina
lg = Image.open(HERE + 'logo-source.png').convert('RGBA')
a = lg.getchannel('A').point(lambda v: 0 if v < 40 else v)
lg.putalpha(a)
x0, y0, x1, y1 = a.getbbox()
m = 12
lg = lg.crop((max(0, x0 - m), max(0, y0 - m), min(lg.width, x1 + m), min(lg.height, y1 + m)))
lg = lg.resize((800, round(800 * lg.height / lg.width)), Image.LANCZOS)
lg.save(OUT + 'logo.png', optimize=True)

# Icon: rounded-square mask (supersampled) to remove the white corners
ic = Image.open(HERE + 'icon-source.png').convert('RGBA')
W = ic.width
S = 4
inset, r = 3, 310
mask = Image.new('L', (W * S, W * S), 0)
ImageDraw.Draw(mask).rounded_rectangle((inset * S, inset * S, (W - inset) * S - 1, (W - inset) * S - 1), r * S, fill=255)
mask = mask.resize((W, W), Image.LANCZOS)
ic.putalpha(mask)

for size in (192, 512):
    ic.resize((size, size), Image.LANCZOS).save(OUT + f'icon-{size}.png', optimize=True)
ic.resize((256, 256), Image.LANCZOS).save(STATIC + 'favicon.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

# Apple touch icon: iOS rounds the corners itself, so fill them with the gradient
src = Image.open(HERE + 'icon-source.png').convert('RGB')
c0, c1 = src.getpixel((150, 150)), src.getpixel((W - 150, W - 150))
bg = Image.new('RGB', (W, W))
px = bg.load()
for y in range(W):
    for x in range(W):
        t = (x + y) / (2 * (W - 1))
        px[x, y] = tuple(round(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
bg.paste(ic, (0, 0), ic)
bg.resize((180, 180), Image.LANCZOS).save(OUT + 'apple-touch-icon.png', optimize=True)

