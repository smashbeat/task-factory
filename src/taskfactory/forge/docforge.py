"""docforge: the PDF forge. Drawing on a reportlab canvas in top-left coordinates, then the production routes a
real supplier's file goes through: digital, distilled (Ghostscript), outlined (no fonts), scans with a right,
wrong or missing OCR layer, sideways scans; and the overlays: stamps, visible corrections. Domain-free: a pack's
renderer draws the clean document with `Pen` and calls `finish` for the route. Runs inside a generator image
(fonts, Ghostscript, Tesseract, OCRmyPDF). Ported from the coa pack's render.py, behaviour unchanged."""
from __future__ import annotations

import io
import os
import random
import shutil
import subprocess
import tempfile

import pikepdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

LETTER = (612.0, 792.0)
A4 = (595.0, 842.0)
SCAN_ROUTES = {"scan_ocr", "scan_wrong_ocr", "scan_no_ocr", "scan_rotated"}
ROUTES = ("digital", "distilled", "outlined", "scan_ocr", "scan_wrong_ocr", "scan_no_ocr", "scan_rotated",
          "form", "form_mismatch")

FONT_FILES = {
    "Liberation": ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    "DejaVuSerif": ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    "Carlito": ("/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
                "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf"),
    "Roboto": ("/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Regular.ttf",
               "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Bold.ttf"),
    "OpenSans": ("/usr/share/fonts/truetype/open-sans/OpenSans-Regular.ttf",
                 "/usr/share/fonts/truetype/open-sans/OpenSans-Bold.ttf"),
}
for fam, (reg, bold) in FONT_FILES.items():
    pdfmetrics.registerFont(TTFont(fam, reg))
    pdfmetrics.registerFont(TTFont(fam + "-Bold", bold))
STAMP_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


# ------------------------------------------------------------------ drawing

class Pen:
    """Top-left coordinates over a reportlab canvas, one house font family."""

    def __init__(self, path, house, size=None):
        self.size = size or house["size"]
        self.c = rl_canvas.Canvas(path, pagesize=self.size, invariant=1)
        self.font = house["font"]
        self.w, self.h = self.size
        self.y = 54
        self.page_no = 1
        self.boxes = []             # (page, x0, top, x1, bottom) of every string drawn, top-left coordinates

    def text(self, x, s, size=10, bold=False, y=None, color=(0, 0, 0), align="left", sup=None, fill=None):
        yy = self.y if y is None else y
        f = self.font + ("-Bold" if bold else "")
        self.c.setFont(f, size)
        self.c.setFillColorRGB(*(fill or color))
        if align == "center":
            x = x - pdfmetrics.stringWidth(s, f, size) / 2
        elif align == "right":
            x = x - pdfmetrics.stringWidth(s, f, size)
        self.c.drawString(x, self.h - yy, s)
        self.boxes.append((self.page_no, x, yy - size, x + pdfmetrics.stringWidth(s, f, size) + (size if sup else 0),
                           yy + size * 0.3))
        if sup:
            sw = pdfmetrics.stringWidth(s, f, size)
            self.c.setFont(f, size * 0.6)
            self.c.drawString(x + sw + 0.5, self.h - yy + size * 0.38, sup)
        self.c.setFillColorRGB(0, 0, 0)
        return yy

    def width(self, s, size=10, bold=False):
        return pdfmetrics.stringWidth(s, self.font + ("-Bold" if bold else ""), size)

    def line(self, x0, x1, y=None, width=0.6):
        yy = self.y if y is None else y
        self.c.setLineWidth(width)
        self.c.line(x0, self.h - yy, x1, self.h - yy)

    def vline(self, x, y0, y1, width=0.6):
        self.c.setLineWidth(width)
        self.c.line(x, self.h - y0, x, self.h - y1)

    def image(self, im, x, y, w, h):
        self.c.drawImage(ImageReader(im), x, self.h - y - h, w, h, mask="auto")

    def new_page(self, size=None):
        self.c.showPage()
        if size:
            self.size = size
            self.c.setPageSize(size)
            self.w, self.h = size
        self.y = 54
        self.page_no += 1

    def save(self):
        self.c.showPage()
        self.c.save()


def wrap(pen, s, w, size):
    words, lines, cur = s.split(" "), [], ""
    for word in words:
        cand = (cur + " " + word).strip()
        if pen.width(cand, size) <= w - 6 or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


# ------------------------------------------------------------------ production routes

def set_meta(path, meta):
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        for k, val in meta.items():
            pdf.docinfo[pikepdf.Name("/" + k)] = val
        pdf.save(path)


def rasterize(pdf_path, dpi=300, color=False):
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png"] + ([] if color else ["-gray"]) +
                       [pdf_path, os.path.join(td, "p")], check=True)
        return [Image.open(os.path.join(td, f)).copy() for f in sorted(os.listdir(td))]


def scan_sim(im, rnd):
    im = im.convert("L")
    im = im.rotate(rnd.uniform(-0.5, 0.5), resample=Image.BICUBIC, expand=False, fillcolor=250)
    noisy = Image.effect_noise(im.size, 7).convert("L")
    im = Image.blend(im, noisy, 0.07)
    return im.filter(ImageFilter.GaussianBlur(0.45))


def jpeg_bytes(im, q=82):
    b = io.BytesIO()
    im.save(b, format="JPEG", quality=q)
    return b.getvalue()


def image_pdf(images, path, page_size, rotate=0):
    cv = rl_canvas.Canvas(path, pagesize=page_size, invariant=1)
    for im in images:
        w, h = page_size
        if im.width > im.height and w < h:
            w, h = h, w
            cv.setPageSize((w, h))
        if rotate:
            cv.setPageSize((h, w))
            cv.drawImage(ImageReader(io.BytesIO(jpeg_bytes(im))), 0, 0, h, w)
        else:
            cv.drawImage(ImageReader(io.BytesIO(jpeg_bytes(im))), 0, 0, w, h)
        cv.showPage()
    cv.save()
    if rotate:
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            for p in pdf.pages:
                p.Rotate = rotate
            pdf.save(path)


def ocr_layer(src, dst):
    subprocess.run(["ocrmypdf", "-q", "--output-type", "pdf", "--optimize", "0", "-l", "eng", src, dst],
                   check=True)


def replace_page_images(path, images):
    """Swap each page's scanned image for another raster of the same size (OCR layer stays)."""
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        for page, im in zip(pdf.pages, images):
            for name, xo in page.Resources.XObject.items():
                if xo.get("/Subtype") == "/Image":
                    xo.write(jpeg_bytes(im), filter=pikepdf.Name.DCTDecode)
                    xo.Width, xo.Height = im.width, im.height
                    xo.ColorSpace = pikepdf.Name.DeviceGray
                    xo.BitsPerComponent = 8
                    for k in ("/DecodeParms", "/SMask"):
                        if k in xo:
                            del xo[k]
        pdf.save(path)


def finish(route, base, path, rnd, meta, size, wrong_base=None):
    """Produce `path` from the clean `base` PDF through `route`. `meta` is the house's producer metadata and
    `size` its page size. For scan_wrong_ocr, `wrong_base()` is called once the page seeds are drawn and returns
    a base PDF with altered values: the OCR layer is read from it while the page images stay right."""
    td = tempfile.mkdtemp()
    if route == "digital":
        shutil.copy(base, path)
        set_meta(path, meta)
    elif route == "distilled":
        subprocess.run(["gs", "-q", "-o", path, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.6", base], check=True)
        set_meta(path, {k: v for k, v in meta.items() if k != "Producer"})
    elif route == "outlined":
        subprocess.run(["gs", "-q", "-o", path, "-sDEVICE=pdfwrite", "-dNoOutputFonts", base], check=True)
        set_meta(path, {"Creator": "Adobe Illustrator 27.0 (Windows)"})
    elif route in SCAN_ROUTES:
        raws = rasterize(base)
        seeds = [rnd.random() for _ in raws]
        pages = [scan_sim(im, random.Random(sd)) for im, sd in zip(raws, seeds)]
        if route == "scan_rotated":
            # fed sideways: the page displays turned a quarter, as the scanner wrote it
            pages = [im.rotate(90, expand=True) for im in pages]
            image_pdf(pages, path, (size[1], size[0]))
            set_meta(path, meta)
        elif route == "scan_no_ocr":
            image_pdf(pages, path, size)
            set_meta(path, meta)
        else:
            if route == "scan_wrong_ocr":
                wbase = wrong_base()
                ocr_src = [scan_sim(im, random.Random(sd)) for im, sd in zip(rasterize(wbase), seeds)]
            else:
                ocr_src = pages
            img = os.path.join(td, "img.pdf")
            image_pdf(ocr_src, img, size)
            set_meta(img, meta)
            ocr_layer(img, path)
            if route == "scan_wrong_ocr":
                replace_page_images(path, pages)
    else:
        raise ValueError(route)
    shutil.rmtree(td)


# ------------------------------------------------------------------ overlays

def stamp_image(text, rnd):
    font = ImageFont.truetype(STAMP_FONT, 44)
    tw = int(font.getlength(text)) + 50
    im = Image.new("RGBA", (tw, 100), (255, 255, 255, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([3, 3, tw - 4, 96], outline=(150, 20, 30, 230), width=5)
    d.text((24, 22), text, fill=(150, 20, 30, 230), font=font)
    return im.rotate(rnd.uniform(-4, 4), expand=True, resample=Image.BICUBIC)


def clear_spot(boxes, page_w, page_h, sw, sh, page=1, y_from=112, x=None):
    """The highest place at the right margin of `page` where a stamp of sw by sh covers no drawn string.
    `boxes` are a Pen's boxes after a dry draw."""
    words = [b for b in boxes if b[0] == page]
    sx = page_w - 54 - sw if x is None else x
    clear = lambda y: not any(b[1] < sx + sw + 4 and b[3] > sx - 4 and b[2] < y + sh + 4 and b[4] > y - 4
                              for b in words)
    sy = next((y for y in range(y_from, int(page_h / 2)) if clear(y)), y_from)
    return sx, sy


def freetext_correction(path, page_index, rect, text):
    """An opaque FreeText annotation over a printed value, as a reviewer's correction."""
    x0, y0, x1, y1 = rect
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        page = pdf.pages[page_index]
        ap = pikepdf.Stream(pdf, (f"q 1 1 1 rg 0 0 {x1 - x0:.2f} {y1 - y0:.2f} re f 0 0 0.6 rg BT /Helv 9.5 Tf 2 "
                                  f"{(y1 - y0) * 0.28:.2f} Td ({text}) Tj ET Q").encode())
        ap.Type = pikepdf.Name.XObject
        ap.Subtype = pikepdf.Name.Form
        ap.BBox = [0, 0, x1 - x0, y1 - y0]
        ap.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(Helv=pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica,
            Encoding=pikepdf.Name.WinAnsiEncoding)))
        annot = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.FreeText, Rect=[x0, y0, x1, y1],
            Contents=pikepdf.String(text), DA=pikepdf.String("0 0 0.6 rg /Helv 9.5 Tf"), F=4,
            T=pikepdf.String("QA reviewer"), AP=pikepdf.Dictionary(N=ap)))
        if "/Annots" not in page:
            page.Annots = pdf.make_indirect(pikepdf.Array())
        page.Annots.append(annot)
        pdf.save(path)


def page_count(path):
    import fitz
    return len(fitz.open(path))


def find_word(path, word, page_index=0, occurrence=-1, missing_ok=False):
    """Position of a printed string, in PDF user space (bottom-left origin)."""
    import fitz
    doc = fitz.open(path)
    page = doc[page_index]
    hits = page.search_for(word)
    if not hits and missing_ok:
        return None
    r = hits[occurrence]
    h = page.rect.height
    return (r.x0, h - r.y1, r.x1, h - r.y0)
