"""Upload validation and safe SVG/PDF import boundaries."""
from __future__ import annotations
from pathlib import Path
import re
import math
from defusedxml import ElementTree as SafeET

EXT = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".eps", ".pdf", ".ai"}
SVG_NS = "http://www.w3.org/2000/svg"
BLOCKED = {"script", "foreignObject", "image", "use", "a", "iframe", "object", "embed", "filter", "animate", "set", "animateMotion", "animateTransform"}
LINK_ATTRS = {"href", "src"}
URL_RE = re.compile(r"url\s*\(", re.I)


def local(tag: str) -> str:
    return tag.split("}")[-1].split(":")[-1]


def validate_svg(raw: bytes) -> bytes:
    if len(raw) > 4_000_000:
        raise ValueError("SVG exceeds 4 MB parsing limit")
    root = SafeET.fromstring(raw)
    if local(root.tag) != "svg":
        raise ValueError("Not an SVG root")
    # Validate declared geometry *before* CairoSVG raster allocation.
    def dimension(raw):
        if raw is None: return None
        match=re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt|mm|cm|in)?\s*", raw)
        if not match:raise ValueError("Invalid SVG dimensions")
        amount=float(match.group(1))
        factor={None:1,"px":1,"pt":96/72,"mm":96/25.4,"cm":96/2.54,"in":96}[match.group(2)]
        return amount*factor
    width,height=dimension(root.get("width")),dimension(root.get("height"))
    vb=root.get("viewBox")
    if vb:
        try:
            values=[float(v) for v in re.split(r"[,\s]+",vb.strip())]
            if len(values)!=4 or values[2]<=0 or values[3]<=0 or not all(math.isfinite(v) for v in values):
                raise ValueError()
        except ValueError:raise ValueError("Invalid SVG viewBox")
        if width is None:width=values[2]
        if height is None:height=values[3]
    if width is None or height is None or not all(math.isfinite(v) for v in [width,height]) or min(width,height)<1 or max(width,height)>10000 or width*height>16000000:
        raise ValueError("SVG exceeds geometry safety limits")
    elements = list(root.iter())
    if len(elements) > 20000:
        raise ValueError("Too many SVG nodes")
    for n in elements:
        if local(n.tag) in BLOCKED:
            raise ValueError(f"Unsafe or unsupported SVG node: {local(n.tag)}")
        for key, value in n.attrib.items():
            k = local(key).lower()
            if k in LINK_ATTRS or k.startswith("on") or URL_RE.search(str(value)):
                raise ValueError("SVG external reference, URL, or event handler rejected")
            if k == "style" and ("@import" in value or "expression" in value.lower()):
                raise ValueError("Unsafe SVG style")
        if local(n.tag) == "style":
            raise ValueError("Embedded stylesheets are not supported in safe SVG mode")
    # parse+serialize strips any XML processing instructions and malicious entities
    import xml.etree.ElementTree as ET
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def detect_format(filename: str, data: bytes) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    if suffix not in EXT:
        raise ValueError("Unsupported file extension")
    kind = suffix.lstrip(".")
    if suffix == ".ai":
        if data.startswith(b"%PDF-"):
            return "pdf", "PDF-compatible Illustrator artwork; proprietary AI editing metadata is not preserved"
        raise ValueError("Non-PDF Illustrator .ai requires a PDF-compatible re-export")
    if kind == "svg":
        validate_svg(data)
    elif kind == "pdf" and not data.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF signature")
    elif kind == "eps" and not (data.startswith(b"%!PS") or data.startswith(b"\xc5\xd0\xd3\xc6")):
        raise ValueError("Invalid EPS signature")
    else:
        from io import BytesIO
        from PIL import Image
        if kind in {"png", "jpg", "jpeg", "webp"}:
            try:
                with Image.open(BytesIO(data)) as im:
                    im.verify()
            except Exception as exc:
                raise ValueError("Invalid raster image") from exc
    return kind, ""


def safe_uuid(value: str) -> str:
    import uuid
    try:
        return uuid.UUID(value).hex
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid identifier") from exc
