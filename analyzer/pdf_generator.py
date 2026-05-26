"""Generate polished PDF reports using Playwright (Chromium print-to-PDF)."""
from __future__ import annotations

import io


def _compress_pdf(pdf_bytes: bytes) -> bytes:
    """Shrink PDF streams so viewers scroll more smoothly."""
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(pdf_bytes))
        writer = PdfWriter()
        for page in reader.pages:
            page.compress_content_streams(level=9)
            writer.add_page(page)
        writer.compress_identical_objects(remove_identicals=True)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:
        return pdf_bytes


def html_to_pdf(html: str) -> bytes:
    """
    Render HTML in headless Chromium and export as PDF.
    Uses vector-friendly CSS (no gradients/shadows) for smooth scrolling.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=False,
                margin={
                    "top": "12mm",
                    "right": "10mm",
                    "bottom": "14mm",
                    "left": "10mm",
                },
            )
            return _compress_pdf(pdf_bytes)
        finally:
            browser.close()
