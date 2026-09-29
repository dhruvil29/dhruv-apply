"""Minimal Markdown -> styled, print-ready HTML (for CV / cover letter)."""
import html
import re

CSS = """
:root { --ink:#1a1a1a; --muted:#555; --accent:#0f4c81; }
* { box-sizing:border-box; }
body { font-family: Georgia, 'Times New Roman', serif; color:var(--ink);
       line-height:1.45; margin:0; background:#fff; }
main { max-width:720px; margin:0 auto; padding:48px 40px; }
h1 { font-size:1.7em; margin:0 0 2px; }
h1 + p { color:var(--muted); font-size:.92em; margin:0 0 18px; }
h2 { font-size:1.05em; text-transform:uppercase; letter-spacing:.08em;
     color:var(--accent); border-bottom:1px solid #ccc;
     margin:22px 0 8px; padding-bottom:4px; }
h3 { font-size:1em; margin:12px 0 2px; }
p { margin:6px 0; }
ul { margin:6px 0 10px; padding-left:20px; }
li { margin:3px 0; }
@media print {
  main { padding:0; max-width:none; }
  body { font-size:11pt; }
  h2 { break-after:avoid; }
  li, p { break-inside:avoid; }
}
"""


def _inline(text):
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text


def md_to_html(md):
    out = []
    in_list = False
    for raw in md.split("\n"):
        line = raw.strip()
        if line.startswith("### "):
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
        elif not line:
            if in_list:
                out.append("</ul>"); in_list = False
        else:
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<p>{_inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def render_page(title, md_body):
    body = md_to_html(md_body)
    safe_title = html.escape(title)
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{safe_title}</title><style>{CSS}</style></head>"
            f"<body><main>{body}</main></body></html>")
