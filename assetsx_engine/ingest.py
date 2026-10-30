"""Converts supported uploads to bounded RGBA previews without claiming all sources are editable vectors."""
from __future__ import annotations
import io
import subprocess
import tempfile
from pathlib import Path
import fitz
from PIL import Image, ImageOps, UnidentifiedImageError
import cairosvg
from .security import validate_svg


def preview(data: bytes, kind: str, max_pixels: int) -> tuple[Image.Image, str, list[str]]:
    warnings: list[str] = []
    origin = "raster"
    try:
        if kind in {"png", "jpeg", "jpg", "webp"}:
            Image.MAX_IMAGE_PIXELS = max_pixels
            im = Image.open(io.BytesIO(data))
            if im.width * im.height > max_pixels:
                raise ValueError("Image exceeds pixel limit")
            im = ImageOps.exif_transpose(im).convert("RGBA")
        elif kind == "svg":
            origin = "vector_svg"
            safe = validate_svg(data)
            png = cairosvg.svg2png(bytestring=safe, output_width=None, output_height=None)
            im = Image.open(io.BytesIO(png)).convert("RGBA")
        elif kind == "pdf":
            origin = "vector_pdf_mixed"
            doc = fitz.open(stream=data, filetype="pdf")
            if doc.page_count < 1 or doc.page_count > 100:
                raise ValueError("Unsupported PDF page count")
            page = doc[0]
            if page.rect.width * page.rect.height > max_pixels:
                zoom = (max_pixels / (page.rect.width * page.rect.height)) ** 0.5
            else:
                zoom = min(2, (max_pixels / max(1, page.rect.width * page.rect.height)) ** 0.5)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom,zoom), alpha=True)
            im = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")
            warnings.append("PDF: first page only for editing; original vector content retained for reference")
        elif kind == "eps":
            origin = "eps_raster_import"
            # Isolated subprocess is still recommended in a sandboxed container for untrusted EPS.
            with tempfile.TemporaryDirectory() as td:
                source = Path(td)/"source.eps"
                rendered = Path(td)/"render.png"
                source.write_bytes(data)
                subprocess.run(["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dEPSCrop", "-sDEVICE=pngalpha", "-r144", f"-sOutputFile={rendered}", str(source)], check=True, timeout=30, capture_output=True)
                im = Image.open(rendered).convert("RGBA")
            warnings.append("EPS preview is rasterized; curves are retraced rather than repaired in place")
        else:
            raise ValueError("Unsupported image type")
        if im.width < 1 or im.height < 1 or im.width * im.height > max_pixels:
            raise ValueError("Asset exceeds safe pixel limits")
        if im.width > 10000 or im.height > 10000:
            raise ValueError("Dimensions exceed safe limit")
        im.load()
        return im, origin, warnings
    except (fitz.FileDataError, UnidentifiedImageError, OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"Import failed: {type(exc).__name__}") from exc
