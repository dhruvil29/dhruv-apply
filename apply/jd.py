"""Fetch a job description from a URL or local file; return clean text."""
import re
import urllib.request
from html.parser import HTMLParser

_SKIP = {"script", "style", "nav", "header", "footer", "aside"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def clean_html(html):
    p = _Text()
    p.feed(html)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_jd(source):
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(
            source, headers={"User-Agent": "Mozilla/5.0 (dhruv-apply)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
        text = clean_html(raw)
    else:
        with open(source, encoding="utf-8") as f:
            text = f.read().strip()
    if len(text) < 200:
        raise SystemExit("Could not extract a usable job description "
                         f"from {source} (only {len(text)} chars). "
                         "Paste the posting into a text file and use --jd <file>.")
    return text[:12000]
