"""Getting a picture ready to be sent to Cloudflare as a reference (spec Part 12, section 5).

Cloudflare wants every reference picture smaller than 512x512, so whatever the person put in the outfit
folder is shrunk before it leaves the machine. Pillow is imported only when this actually runs — a program
with photos switched off never loads it.
"""
import io

REFERENCE_LIMIT = 511  # both sides; the service wants "< 512"


def shrink_reference(data):
    """The same picture, at most 511 pixels on each side (aspect kept), as JPEG bytes."""
    from PIL import Image

    picture = Image.open(io.BytesIO(data)).convert("RGBA")
    flat = Image.new("RGB", picture.size, (255, 255, 255))  # a see-through background becomes white, not black
    flat.paste(picture, mask=picture.getchannel("A"))
    picture = flat
    picture.thumbnail((REFERENCE_LIMIT, REFERENCE_LIMIT))
    out = io.BytesIO()
    picture.save(out, format="JPEG", quality=90)
    return out.getvalue()
