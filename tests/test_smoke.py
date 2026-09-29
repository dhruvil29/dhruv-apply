"""Smoke tests: CLI plumbing and HTML renderer (no LLM calls)."""
import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apply import render  # noqa: E402
from apply.__main__ import main  # noqa: E402


def test_md_to_html_sections():
    html = render.md_to_html("# Jane\n## Skills\n- Python\n- Go\nSome **bold** text")
    assert "<h1>Jane</h1>" in html
    assert "<h2>Skills</h2>" in html
    assert "<li>Python</li>" in html
    assert "<strong>bold</strong>" in html
    assert "<script>" not in html  # escaping check


def test_render_page_is_complete_document():
    page = render.render_page("CV", "# Hi")
    assert page.startswith("<!doctype html>")
    assert "<style>" in page and "</html>" in page


def test_cli_help_exits_zero():
    import pytest
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0


def test_tracker_csv_logic():
    import apply.commands as c
    with tempfile.TemporaryDirectory() as tmp:
        class A:  # minimal argparse namespace
            action = "add"; company = "Acme"; role = "Backend"
            url = "https://x.example"; notes = ""; id = None; status = None
        c.cmd_track(A(), tmp)
        p = os.path.join(tmp, "tracker", "applications.csv")
        assert os.path.exists(p)
        with open(p, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["company"] == "Acme" and rows[0]["status"] == "applied"

        class S:
            action = "set"; id = "1"; status = "interview"; notes = ""
        c.cmd_track(S(), tmp)
        with open(p, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["status"] == "interview"
