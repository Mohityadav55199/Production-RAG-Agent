"""Helpers that build real images and documents for the image tests."""

import base64
import io
import os

import pymupdf
from PIL import Image


def png(width=300, height=300, noise=True, mode="RGB") -> bytes:
    """A PNG. Noise keeps it from compressing to nothing, like a real photo or chart."""
    if noise:
        channels = len(mode)
        img = Image.frombytes(mode, (width, height), os.urandom(width * height * channels))
    else:
        img = Image.new(mode, (width, height), "white")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def encoded(fmt: str, width=200, height=120, mode="RGB", **save_args) -> bytes:
    img = Image.new(mode, (width, height), (200, 60, 60, 255) if len(mode) == 4 else "red")
    out = io.BytesIO()
    img.save(out, format=fmt, **save_args)
    return out.getvalue()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def pdf_with_images(pages: list[dict]) -> bytes:
    """pages: [{"text": str, "images": [png bytes, ...]}]. Images are laid out side by side."""
    doc = pymupdf.open()
    for spec in pages:
        page = doc.new_page()
        if spec.get("text"):
            # A wrapped box: text on a single long line would run off the page, and PyMuPDF drops text
            # outside the page when extracting.
            page.insert_textbox(pymupdf.Rect(72, 72, 540, 380), spec["text"], fontsize=8)
        for i, data in enumerate(spec.get("images", [])):
            x = 72 + i * 230
            page.insert_image(pymupdf.Rect(x, 400, x + 200, 600), stream=data)
    out = doc.tobytes()
    doc.close()
    return out


SENTENCE = "The quarterly report describes revenue growth across all regions and the plan for next year. "
