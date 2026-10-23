"""Generate the app's original water/leaf mark with Pillow (no external assets)."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / 'static' / 'pwa'
OUT.mkdir(parents=True, exist_ok=True)


def curve(start, first, second, end):
    return [tuple((1-t)**3*start[i] + 3*(1-t)**2*t*first[i] +
                  3*(1-t)*t*t*second[i] + t**3*end[i] for i in (0, 1))
            for t in [n/80 for n in range(81)]]


def icon(size, filename):
    scale = 4
    image = Image.new('RGB', (size*scale, size*scale), '#1B4332')
    draw = ImageDraw.Draw(image)
    def points(values):
        return [(round(x*size*scale/512), round(y*size*scale/512)) for x, y in values]
    drop = (curve((256, 102), (235, 139), (151, 223), (151, 294)) +
            curve((151, 294), (151, 431), (361, 431), (361, 294)) +
            curve((361, 294), (361, 223), (277, 139), (256, 102)))
    draw.polygon(points(drop), fill='#F5F0E8')
    leaf = curve((250, 321), (244, 259), (277, 240), (313, 239)) + curve((313, 239), (317, 284), (293, 321), (250, 321))
    draw.polygon(points(leaf), fill='#5B8A64')
    draw.line(points(curve((238, 354), (247, 318), (271, 284), (291, 264))), fill='#1B4332', width=round(size*scale*9/512))
    image.resize((size, size), Image.Resampling.LANCZOS).save(OUT / filename, optimize=True)


for size, filename in [(192, 'icon-192.png'), (512, 'icon-512.png'),
                       (512, 'icon-maskable-512.png'), (180, 'apple-touch-icon.png')]:
    icon(size, filename)
print('Generated four PWA icons in', OUT)
