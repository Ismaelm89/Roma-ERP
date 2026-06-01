# -*- coding: utf-8 -*-
"""Convert the Arabic training Markdown files to styled RTL HTML for PDF printing."""
import re
import markdown

BASE = r'C:\Users\MahmoudIsmael\Desktop\Roma-ERP\docs'

# (source markdown, output html, page title)
DOCS = [
    (
        BASE + r'\دليل-تدريب-المستخدمين.md',
        BASE + r'\_دليل-تدريب-المستخدمين.html',
        'دليل تدريب مستخدمي نظام Roma ERP',
    ),
    (
        BASE + r'\دليل-الأرصدة-الافتتاحية.md',
        BASE + r'\_دليل-الأرصدة-الافتتاحية.html',
        'دليل تسجيل الأرصدة الافتتاحية — نظام Roma ERP',
    ),
]

STYLE = """
  @page { size: A4; margin: 18mm 16mm; }
  * { box-sizing: border-box; }
  body {
    font-family: "Segoe UI", Tahoma, "Arial", sans-serif;
    direction: rtl; text-align: right;
    color: #1f2937; line-height: 1.8; font-size: 13px;
  }
  h1 { font-size: 26px; color: #1d4ed8; border-bottom: 3px solid #1d4ed8;
        padding-bottom: 8px; margin-top: 6px; }
  h1:first-of-type { text-align: center; }
  h2 { font-size: 20px; color: #0f766e; margin-top: 26px;
        border-right: 5px solid #0f766e; padding-right: 10px; }
  h3 { font-size: 15px; color: #b45309; margin-top: 16px; }
  hr { border: none; border-top: 1px dashed #cbd5e1; margin: 22px 0; }
  ul, ol { padding-right: 24px; }
  li { margin: 4px 0; }
  strong { color: #b91c1c; }
  code { background: #f1f5f9; padding: 1px 5px; border-radius: 4px;
          font-family: Consolas, monospace; direction: ltr; display: inline-block; }
  blockquote { background: #fffbeb; border-right: 5px solid #f59e0b;
                margin: 12px 0; padding: 8px 14px; border-radius: 0 6px 6px 0;
                color: #92400e; }
  blockquote strong { color: #92400e; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; }
  th, td { border: 1px solid #cbd5e1; padding: 6px 10px; text-align: right; }
  th { background: #eff6ff; color: #1d4ed8; }
  figure.shot {
    margin: 14px 0 20px; text-align: center; page-break-inside: avoid;
  }
  figure.shot img {
    max-width: 100%; border: 1px solid #94a3b8; border-radius: 8px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.12);
  }
  figure.shot figcaption {
    margin-top: 6px; font-size: 11px; color: #64748b; font-style: normal;
    background: #f1f5f9; display: inline-block; padding: 3px 12px;
    border-radius: 12px;
  }
"""


def figure(m):
    """Turn a markdown <img> into a <figure> block with a caption from the alt text."""
    tag = m.group(0)
    src_m = re.search(r'src="(.*?)"', tag)
    alt_m = re.search(r'alt="(.*?)"', tag)
    src = src_m.group(1) if src_m else ''
    alt = alt_m.group(1) if alt_m else ''
    cap = f'<figcaption>{alt}</figcaption>' if alt else ''
    return f'<figure class="shot"><img src="{src}" alt="{alt}" />{cap}</figure>'


def convert(src, out, title):
    with open(src, encoding='utf-8') as f:
        md_text = f.read()

    html_body = markdown.markdown(
        md_text,
        extensions=['tables', 'fenced_code', 'sane_lists', 'nl2br'],
    )

    html_body = re.sub(r'<img\b[^>]*?>', figure, html_body)
    # unwrap <p>...</p> that only wraps a figure
    html_body = re.sub(r'<p>\s*(<figure class="shot">.*?</figure>)\s*</p>',
                       r'\1', html_body, flags=re.S)
    # drop now-empty <p></p>
    html_body = re.sub(r'<p>(\s*(<br\s*/?>)?\s*)+</p>', '', html_body)

    template = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
{STYLE}
</style>
</head>
<body>
{html_body}
</body>
</html>
"""

    with open(out, 'w', encoding='utf-8') as f:
        f.write(template)

    print('HTML written:', out)


if __name__ == '__main__':
    for src, out, title in DOCS:
        convert(src, out, title)
