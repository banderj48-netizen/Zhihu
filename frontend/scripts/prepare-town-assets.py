"""Prepare supplied town artwork without modifying the originals (requires Pillow)."""
from collections import deque
from pathlib import Path
import shutil

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'specimen'
OUTPUT = ROOT / 'public' / 'town'
OUTPUT.mkdir(parents=True, exist_ok=True)

shutil.copyfile(SOURCE / 'townmap.jpg', OUTPUT / 'townmap.jpg')
Image.open(SOURCE / '糕点店.png').convert('RGB').save(OUTPUT / 'bakery.webp', quality=94)


def character(filename):
    # Only the first full-body front view, not the expression / turnaround sheet.
    im = Image.open(SOURCE / filename).convert('RGB').crop((0, 110, 245, 510))
    width, height = im.size
    visible = { (x, y) for y in range(height) for x in range(width) if max(im.getpixel((x, y))) > 28 }
    components = []
    while visible:
        seed = visible.pop()
        component = {seed}
        queue = deque([seed])
        while queue:
            x, y = queue.popleft()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in visible:
                    visible.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    silhouette = max(components, key=len)
    # Fill enclosed details (eyes / nose) so black facial features stay opaque.
    exterior = set()
    queue = deque([(0, 0)])
    while queue:
        x, y = queue.popleft()
        if not (0 <= x < width and 0 <= y < height) or (x, y) in silhouette or (x, y) in exterior:
            continue
        exterior.add((x, y))
        queue.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
    alpha = Image.new('L', im.size)
    alpha.putdata([0 if (x, y) in exterior else 255 for y in range(height) for x in range(width)])
    im.putalpha(alpha)
    return im


def tint(im, kind):
    result = im.copy()
    mask = Image.new('L', im.size)
    draw = ImageDraw.Draw(mask)
    if kind == 'denim':
        draw.polygon([(57, 151), (107, 172), (116, 270), (67, 281), (51, 262)], fill=255)
        draw.polygon([(144, 171), (196, 150), (210, 254), (194, 282), (139, 281)], fill=255)
    else:
        draw.rectangle((40, 154, 219, 321), fill=255)
        draw.rectangle((130, 35, 204, 98), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(1))
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = im.getpixel((x, y))
            amount = mask.getpixel((x, y)) / 255
            if not a or not amount:
                continue
            if kind == 'denim' and max(r, g, b) < 158:
                light = (r + g + b) / 3 / 95
                color = [min(255, round(v * light)) for v in (62, 106, 157)]
            elif kind == 'mint' and r > g * 1.075 and r > b * 1.075:
                light = (r + g + b) / 3 / 185
                color = [min(255, round(v * light)) for v in (147, 190, 170)]
            else:
                continue
            result.putpixel((x, y), tuple(round(v * amount + old * (1 - amount)) for v, old in zip(color, (r, g, b))) + (a,))
    return result


def save(im, name):
    im = im.crop(im.getbbox())
    im.thumbnail((282, 442), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (320, 480))
    canvas.alpha_composite(im, ((320 - im.width) // 2, 462 - im.height))
    canvas.save(OUTPUT / f'kanshan-{name}.webp', lossless=True)


male = character('男看山.png')
female = character('女看山.png')
save(male, 'field')
save(tint(male, 'denim'), 'denim')
save(female, 'strawberry')
save(tint(female, 'mint'), 'mint')
print('Prepared town, bakery and four transparent outfit sprites in public/town.')
