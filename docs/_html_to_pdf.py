# -*- coding: utf-8 -*-
"""Render the generated guide HTML files to A4 PDFs via headless Chromium.
Run AFTER _md_to_html.py (and after screenshots exist) so images are embedded."""
import os
from playwright.sync_api import sync_playwright

BASE = r'C:\Users\MahmoudIsmael\Desktop\Roma-ERP\docs'

# (html source, pdf output)
DOCS = [
    (BASE + r'\_دليل-تدريب-المستخدمين.html', BASE + r'\دليل-تدريب-المستخدمين.pdf'),
    (BASE + r'\_دليل-الأرصدة-الافتتاحية.html', BASE + r'\دليل-الأرصدة-الافتتاحية.pdf'),
]

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    for src, out in DOCS:
        page.goto('file:///' + src.replace('\\', '/'), wait_until='networkidle')
        page.pdf(
            path=out,
            format='A4',
            print_background=True,
            margin={'top': '18mm', 'bottom': '18mm', 'left': '16mm', 'right': '16mm'},
        )
        print('PDF written:', out)
    browser.close()
