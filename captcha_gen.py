import random
import io
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def generate_math_captcha():
    ops = [
        (random.randint(1, 15), random.randint(1, 15), '+'),
        (random.randint(5, 20), random.randint(1, 10), '-'),
        (random.randint(2, 9), random.randint(2, 9), '*'),
    ]
    a, b, op = random.choice(ops)

    if op == '+':
        answer = a + b
        text = f"{a} + {b} = ?"
    elif op == '-':
        answer = a - b
        text = f"{a} - {b} = ?"
    else:
        answer = a * b
        text = f"{a} × {b} = ?"

    width, height = 320, 120
    bg_color = (245, 245, 245)
    img = Image.new('RGB', (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    for _ in range(2000):
        x = random.randint(0, width)
        y = random.randint(0, height)
        r = random.randint(150, 220)
        draw.point((x, y), fill=(r, r, r))

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
    except:
        try:
            font = ImageFont.truetype("arial.ttf", 42)
        except:
            font = ImageFont.load_default()

    for i, char in enumerate(text):
        x = 30 + i * 38
        y = 35 + random.randint(-8, 8)
        color = (random.randint(20, 80), random.randint(20, 80), random.randint(20, 80))
        draw.text((x, y), char, fill=color, font=font)

    for _ in range(6):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        draw.line(
            (x1, y1, x2, y2),
            fill=(random.randint(100, 180), random.randint(100, 180), random.randint(100, 180)),
            width=2,
        )

    img = img.filter(ImageFilter.GaussianBlur(radius=0.8))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf, str(answer)
