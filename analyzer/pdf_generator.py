"""Generate polished PDF reports using Playwright (Chromium print-to-PDF)."""
from __future__ import annotations

import io


def _compress_pdf(pdf_bytes: bytes) -> bytes: 
    """Shrink PDF streams so viewers scroll more smoothly."""
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(pdf_bytes))            #read pdf(pdf bytes)
        writer = PdfWriter()                                 #writes new pdf
        for page in reader.pages:
            page.compress_content_streams(level=9)           #compress each page's content
            writer.add_page(page) 
        writer.compress_identical_objects(remove_identicals=True) #if the same object appears many times like a logo or image, store it
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()                                #return compressed PDF.
    except Exception:
        return pdf_bytes


def html_to_pdf(html: str) -> bytes: #this helps in rendering HTML in headless Chromium and exporting as PDF. Playwright library provides a high-level API to control headless browsers.
    """
    Render HTML in headless Chromium and export as PDF.
    Uses vector-friendly CSS (no gradients/shadows) for smooth scrolling.
    """ 
    from playwright.sync_api import sync_playwright          #load playwright

    with sync_playwright() as playwright:                    #start playwright session
        browser = playwright.chromium.launch(headless=True)  #launch headless Chromium
        try:
            page = browser.new_page()                        #create a new page
            page.set_content(html, wait_until="load")        #set the HTML content of the page and wait until it is fully loaded
            pdf_bytes = page.pdf(                            #tells chromium to take this page and print it to PDF with the specified options like A4 size, margins, etc
                format="A4",
                print_background=True,                       #ensures any bkg colors or images in the HTML are included in the PDF
                prefer_css_page_size=False,
                margin={
                    "top": "12mm",
                    "right": "10mm",
                    "bottom": "14mm",
                    "left": "10mm",
                },
            )
            return _compress_pdf(pdf_bytes)                  #return final pdf [after compressing(using the function above this)]
        finally:
            browser.close()
