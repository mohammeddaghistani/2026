import re
try:
    import fitz
except ModuleNotFoundError:
    import pymupdf as fitz

from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
from io import BytesIO
import shutil

_tesseract = shutil.which("tesseract")
if _tesseract:
    pytesseract.pytesseract.tesseract_cmd = _tesseract


def preprocess_image(img: Image.Image) -> Image.Image:
    img = img.convert("L")
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2.0)
    enhancer = ImageEnhance.Sharpness(img)
    img = enhancer.enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)
    img = img.filter(ImageFilter.MedianFilter(3))
    threshold = 180
    img = img.point(lambda p: 255 if p > threshold else 0)
    return img


def extract_text_from_pdf(pdf_bytes: bytes, lang: str = "ara+eng") -> str:
    text = ""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        page_text = page.get_text().strip()
        if len(page_text) > 20:
            text += page_text + "\n"
        else:
            pix = page.get_pixmap(dpi=400)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img = preprocess_image(img)
            text += pytesseract.image_to_string(img, lang=lang) + "\n"
    doc.close()
    return text.strip()


def extract_text_from_image(image_bytes: bytes, lang: str = "ara+eng") -> str:
    img = Image.open(BytesIO(image_bytes))

    w, h = img.size
    if max(w, h) > 2000:
        ratio = 2000 / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    gray = img.convert("L")
    enhancer = ImageEnhance.Contrast(gray)
    gray = enhancer.enhance(1.5)
    gray = gray.filter(ImageFilter.SHARPEN)
    gray = gray.filter(ImageFilter.MedianFilter(3))

    text = pytesseract.image_to_string(gray, lang=lang)
    return text.strip()
