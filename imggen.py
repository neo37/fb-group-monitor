"""Картинка с паролем месяца для продажи за Stars."""
import io
from PIL import Image, ImageDraw, ImageFont

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]


def _font(size):
    for p in FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_password_image(password, period_label):
    img = Image.new("RGB", (900, 500), (16, 24, 38))
    d = ImageDraw.Draw(img)
    for y in range(500):  # градиент
        d.line([(0, y), (900, y)], fill=(16, 24, 38 + y // 12))
    d.rounded_rectangle([60, 90, 840, 410], radius=28, outline=(90, 160, 255), width=3)
    d.text((450, 150), "FB MONITOR · ДОСТУП", font=_font(34), fill=(140, 180, 255), anchor="mm")
    d.text((450, 250), password, font=_font(120), fill=(255, 255, 255), anchor="mm")
    d.text((450, 355), f"пароль на {period_label}", font=_font(28), fill=(150, 165, 190), anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
