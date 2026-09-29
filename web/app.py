#!/usr/bin/env python3
"""dhruv-apply web UI: multi-user AI job-application assistant. Stdlib only.

Each user gets an isolated workspace: own profile, own outputs, own tracker.
Admins manage accounts but cannot read anyone's data.

Run:  python -m web.app serve [--port 8770]
        python -m web.app adduser <name> [--admin]
        python -m web.app resetpw <name>

Env:  DHRUV_APPLY_DATA        data dir (default <repo>/data)
      DHRUV_APPLY_PORT        listen port (default 8770)
      DHRUV_APPLY_ADMIN_USER / DHRUV_APPLY_ADMIN_PASS   bootstrap admin
      APPLY_LLM_BASE_URL / APPLY_LLM_MODEL / APPLY_LLM_API_KEY
"""
import argparse
import csv
import getpass
import hmac
import html
import http.cookies
import http.server
import json
import os
import re
import secrets
import socketserver
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web import auth as auth_mod          # noqa: E402
from web import forms as forms_mod        # noqa: E402
from web import jobs as jobs_mod          # noqa: E402
from apply import profile as profile_mod  # noqa: E402
from apply import render as render_mod    # noqa: E402
from apply import commands as commands_mod  # noqa: E402
from types import SimpleNamespace         # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("DHRUV_APPLY_DATA", os.path.join(REPO, "data"))
PORT = int(os.environ.get("DHRUV_APPLY_PORT", "8770"))
COOKIE_NAME = "dhu_session"

CSS = """
:root{--ink:#1c1c1e;--muted:#6b7280;--accent:#0f4c81;--bg:#f7f7f8;--card:#fff;
--line:#e5e7eb;--ok:#15803d;--warn:#b45309;--bad:#b91c1c}
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
color:var(--ink);background:var(--bg);margin:0;line-height:1.5}
.wrap{max-width:760px;margin:0 auto;padding:20px 16px 60px}
nav{background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;
display:flex;gap:14px;align-items:center;flex-wrap:wrap;position:sticky;top:0}
nav b{color:var(--accent)} nav a{color:var(--ink);text-decoration:none}
nav a:hover{color:var(--accent)} nav .sp{flex:1} nav .u{color:var(--muted);font-size:.9em}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:18px;margin:14px 0}
h1{font-size:1.4em;margin:.2em 0} h2{font-size:1.1em;margin:.4em 0}
label{display:block;font-weight:600;margin:12px 0 4px;font-size:.92em}
input[type=text],input[type=password],input[type=url],textarea,select{
width:100%;padding:10px;border:1px solid var(--line);border-radius:8px;font:inherit}
textarea{min-height:120px;font-family:ui-monospace,monospace;font-size:.9em}
textarea.tall{min-height:220px}
button,.btn{background:var(--accent);color:#fff;border:0;border-radius:8px;
padding:10px 18px;font:inherit;cursor:pointer;display:inline-block;text-decoration:none}
button:hover,.btn:hover{filter:brightness(1.1)}
.btn.ghost{background:#eef2f7;color:var(--ink)}
.hint{color:var(--muted);font-size:.88em} .err{color:var(--bad);font-weight:600}
.ok{color:var(--ok);font-weight:600}
table{width:100%;border-collapse:collapse;font-size:.92em}
td,th{border-bottom:1px solid var(--line);padding:8px 6px;text-align:left}
.pill{display:inline-block;padding:2px 10px;border-radius:20px;font-size:.82em;
background:#eef2f7}
pre{background:#111827;color:#e5e7eb;padding:14px;border-radius:8px;overflow:auto;
font-size:.85em}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:end}
.row>div{flex:1;min-width:140px}
footer{color:var(--muted);font-size:.8em;text-align:center;margin-top:30px}
"""


def h(s):
    return html.escape("" if s is None else str(s), quote=True)


def hmac_compare(a, b):
    return hmac.compare_digest(a or "", b or "")


def page(title, user, body, nav=True):
    nav_html = ""
    if nav and user:
        admin = ' <a href="/admin">Admin</a>' if user.get("is_admin") else ""
        nav_html = (
            "<nav><b>dhruv-apply</b><a href='/app'>Home</a>"
            "<a href='/eval'>Fit check</a><a href='/draft'>Draft</a>"
            "<a href='/interview'>Interview</a><a href='/track'>Tracker</a>"
            f"{admin}<span class='sp'></span><span class='u'>{h(user['username'])}"
            "</span><a href='/password'>Password</a>"
            "<form method='post' action='/logout' style='display:inline;margin:0'>"
            f"<input type='hidden' name='csrf' value='{h(_csrf_for(user))}'>"
            "<button class='btn ghost' style='padding:6px 12px'>Log out</button>"
            "</form></nav>")
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{h(title)} · dhruv-apply</title><style>{CSS}</style></head>"
            f"<body>{nav_html}<div class='wrap'>{body}"
            "<footer>dhruv-apply · local-first · never auto-applies</footer>"
            "</div></body></html>")


# CSRF tokens live on the session row; stash per-request in a tiny cache.
_CSRF = {}


def _csrf_for(user):
    return _CSRF.get(user["username"], "")


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "dhruv-apply/0.2"

    # -- plumbing ----------------------------------------------------
    def log_message(self, *a):
        sys.stderr.write("%s %s\n" % (self.address_string(), " ".join(map(str, a))))

    def _parse(self):
        self._path = urllib.parse.urlparse(self.path).path
        self._q = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query)
        self._form = {}
        self._cookies = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        if self.command == "POST":
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n > 2_000_000:
                n = 2_000_000
            raw = self.rfile.read(n).decode("utf-8", "replace")
            self._form = {k: v[0] for k, v in
                          urllib.parse.parse_qs(raw).items()}

    def _send_html(self, body, status=200, headers=None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, path, cookie=None):
        hdrs = {"Location": path}
        if cookie is not None:
            hdrs["Set-Cookie"] = cookie
        self.send_response(303)
        for k, v in hdrs.items():
            self.send_header(k, v)
        self.end_headers()

    def _cookie(self, token=None):
        if token:
            c = (f"{COOKIE_NAME}={token}; Path=/; HttpOnly; "
                 "SameSite=Lax; Max-Age=86400")
            if self.headers.get("X-Forwarded-Proto", "http") == "https":
                c += "; Secure"
            return c
        return (f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; "
                "Max-Age=0")

    def _user(self):
        morsel = self._cookies.get(COOKIE_NAME)
        token = morsel.value if morsel else None
        user = self.server.auth.get_session(token) if token else None
        if user:
            _CSRF[user["username"]] = self.server.auth.csrf_for_token(token)
        return user

    def _need_login(self):
        user = self._user()
        if not user:
            self._redirect("/login")
            return None
        return user

    def _csrf_ok(self, user):
        return hmac_compare(self._form.get("csrf", ""),
                            _CSRF.get(user["username"], ""))

    def _field(self, name, default=""):
        return self._form.get(name, default)

    # -- routing -----------------------------------------------------
    def do_GET(self):
        self._parse()
        p = self._path
        try:
            if p == "/login":
                return self.r_login()
            if p == "/":
                u = self._user()
                return self._redirect("/app" if u else "/login")
            if p == "/app":
                return self.r_dashboard()
            if p == "/profile":
                return self.r_profile()
            if p in ("/eval", "/draft", "/interview"):
                return self.r_jobform(p[1:])
            if p.startswith("/job/"):
                return self.r_job(p[5:])
            if p.startswith("/files/"):
                return self.r_files(p[7:])
            if p == "/track":
                return self.r_track()
            if p == "/password":
                return self.r_password()
            if p == "/admin":
                return self.r_admin()
            self._send_html(page("Not found", self._user(),
                                 "<div class='card'><h1>404</h1></div>"), 404)
        except BrokenPipeError:
            pass

    def do_POST(self):
        self._parse()
        p = self._path
        try:
            if p == "/login":
                return self.p_login()
            user = self._need_login()
            if not user:
                return
            if p == "/logout":
                return self.p_logout(user)
            if not self._csrf_ok(user):
                return self._send_html(
                    page("Error", user, "<div class='card err'>"
                         "Bad request (CSRF). Please go back and retry.</div>"), 400)
            if p == "/profile":
                return self.p_profile(user)
            if p in ("/eval", "/draft", "/interview"):
                return self.p_jobform(user, p[1:])
            if p == "/track/add":
                return self.p_track_add(user)
            if p == "/track/set":
                return self.p_track_set(user)
            if p == "/password":
                return self.p_password(user)
            if p == "/admin/add":
                return self.p_admin_add(user)
            if p == "/admin/toggle":
                return self.p_admin_toggle(user)
            if p == "/admin/resetpw":
                return self.p_admin_resetpw(user)
            self._redirect("/app")
        except BrokenPipeError:
            pass

    # -- login / logout ----------------------------------------------
    def r_login(self):
        if self._user():
            return self._redirect("/app")
        err = self._q.get("e", [""])[0]
        body = ("<div class='card'><h1>Log in</h1>"
                + (f"<p class='err'>{h(err)}</p>" if err else "") +
                "<form method='post' action='/login'>"
                "<label>Username</label><input type='text' name='username' "
                "autocomplete='username' autofocus>"
                "<label>Password</label><input type='password' name='password' "
                "autocomplete='current-password'>"
                "<p><button>Log in</button></p></form>"
                "<p class='hint'>Accounts are created by your admin. "
                "Your data is private to you.</p></div>")
        self._send_html(page("Log in", None, body, nav=False))

    def p_login(self):
        ip = self.client_address[0]
        now = time.time()
        atts = self.server.login_attempts
        atts[ip] = [t for t in atts.get(ip, []) if now - t < 60]
        if len(atts[ip]) >= 8:
            return self._send_html(page("Slow down", None,
                "<div class='card err'>Too many attempts. Wait a minute.</div>",
                nav=False), 429)
        atts[ip].append(now)
        user = self.server.auth.verify(self._field("username"),
                                       self._field("password"))
        if not user:
            return self._redirect("/login?e=" + urllib.parse.quote(
                "Wrong username or password."))
        token, _csrf = self.server.auth.make_session(user["id"])
        self._redirect("/app", cookie=self._cookie(token))

    def p_logout(self, user):
        morsel = self._cookies.get(COOKIE_NAME)
        if morsel:
            self.server.auth.destroy_session(morsel.value)
        _CSRF.pop(user["username"], None)
        self._redirect("/login", cookie=self._cookie(None))

    # -- dashboard ----------------------------------------------------
    def _user_root(self, user):
        return jobs_mod._user_root(DATA_DIR, user["username"])

    def _profile(self, user):
        try:
            return profile_mod.load(self._user_root(user))
        except SystemExit:
            return None

    def r_dashboard(self):
        user = self._need_login()
        if not user:
            return
        prof = self._profile(user)
        root = self._user_root(user)
        # tracker summary
        rows = self._tracker_rows(root)
        recent = jobs_mod.recent(user["username"])
        prof_card = ("<div class='card'><h2>Profile</h2>" +
            (f"<p class='ok'>✓ {h(prof['name'])} — ready. "
              "<a href='/profile'>Edit</a></p>" if prof else
             "<p class='err'>No profile yet — <a href='/profile'>set it up</a> "
             "before running anything.</p>") + "</div>")
        flow = ("<div class='card'><h2>New application</h2>"
                "<div class='row'>"
                "<div><a class='btn' href='/eval'>1 · Fit check</a></div>"
                "<div><a class='btn' href='/draft'>2 · Draft CV + letter</a></div>"
                "<div><a class='btn' href='/interview'>3 · Interview prep</a></div>"
                "</div><p class='hint'>Paste a job posting or its URL. Drafts are "
                "reviewed for fabrication before you ever see them. Nothing is "
                "ever submitted anywhere.</p></div>")
        tr = "".join(
            f"<tr><td>#{h(r['id'])}</td><td>{h(r['date'])}</td>"
            f"<td>{h(r['role'])} @ {h(r['company'])}</td>"
            f"<td><span class='pill'>{h(r['status'])}</span></td></tr>"
            for r in rows[-8:])
        track_card = ("<div class='card'><h2>Tracker</h2>" +
            (f"<table><tr><th></th><th>Date</th><th>Role</th><th>Status</th></tr>"
             f"{tr}</table>" if rows else "<p class='hint'>Nothing tracked yet.</p>") +
            "<p><a href='/track'>Open tracker</a></p></div>")
        jr = "".join(
            f"<tr><td><a href='/job/{j['id']}'>{h(j['label'][:50])}</a></td>"
            f"<td><span class='pill'>{h(j['status'])}</span></td>"
            f"<td class='hint'>{h(j['kind'])}</td></tr>" for j in recent)
        job_card = ("<div class='card'><h2>Recent runs</h2>" +
            (f"<table>{jr}</table>" if recent else
             "<p class='hint'>No runs yet.</p>") + "</div>")
        self._send_html(page("Home", user, prof_card + flow + track_card + job_card))

    # -- profile ------------------------------------------------------
    def r_profile(self):
        user = self._need_login()
        if not user:
            return
        prof = self._profile(user) or {}
        f = forms_mod.profile_to_form(prof)
        err = self._q.get("e", [""])[0]
        body = ("<div class='card'><h1>Career profile</h1>"
                "<p class='hint'>This is the ground truth every draft is checked "
                "against. Be specific and quantify impact.</p>"
                + (f"<p class='err'>{h(err)}</p>" if err else "") +
                "<form method='post' action='/profile'>"
                f"<input type='hidden' name='csrf' value='{h(_CSRF[user['username']])}'>"
                "<label>Full name *</label>"
                f"<input type='text' name='name' value='{h(f['name'])}'>"
                "<div class='row'><div><label>Location</label>"
                f"<input type='text' name='location' value='{h(f['location'])}'></div>"
                "<div><label>Email *</label>"
                f"<input type='text' name='email' value='{h(f['email'])}'></div></div>"
                "<div class='row'><div><label>Phone</label>"
                f"<input type='text' name='phone' value='{h(f['phone'])}'></div>"
                "<div><label>Links (one per line)</label>"
                f"<textarea name='links' style='min-height:60px'>{h(f['links'])}</textarea></div></div>"
                "<label>Professional summary</label>"
                f"<textarea name='summary' style='min-height:70px'>{h(f['summary'])}</textarea>"
                "<label>Skills (comma separated) *</label>"
                f"<textarea name='skills' style='min-height:60px'>{h(f['skills'])}</textarea>"
                "<label>Experience * <span class='hint'>— one block per role, "
                "blank line between: <code>Role @ Company | dates</code> then "
                "<code>- achievement</code> lines</span></label>"
                f"<textarea name='experience' class='tall'>{h(f['experience'])}</textarea>"
                "<label>Education <span class='hint'>— one per line: "
                "<code>Degree, School | dates</code></span></label>"
                f"<textarea name='education' style='min-height:70px'>{h(f['education'])}</textarea>"
                "<p><button>Save profile</button></p></form></div>")
        self._send_html(page("Profile", user, body))

    def p_profile(self, user):
        try:
            data = forms_mod.form_to_profile(self._form,
                                             self._profile(user))
        except ValueError as e:
            return self._redirect("/profile?e=" + urllib.parse.quote(str(e)))
        profile_mod.save(self._user_root(user), data)
        self._redirect("/app")

    # -- job forms / job status / files --------------------------------
    _KINDS = {"eval": "Fit check", "draft": "Draft CV + cover letter",
              "interview": "Interview prep"}

    def r_jobform(self, kind):
        user = self._need_login()
        if not user:
            return
        if not self._profile(user):
            return self._redirect("/profile?e=" + urllib.parse.quote(
                "Set up your profile first."))
        body = (f"<div class='card'><h1>{self._KINDS[kind]}</h1>"
                "<form method='post' action='/" + kind + "'>"
                f"<input type='hidden' name='csrf' value='{h(_CSRF[user['username']])}'>"
                "<label>Name this run (e.g. Acme — Backend Engineer)</label>"
                "<input type='text' name='label'>"
                "<label>Job posting URL (optional)</label>"
                "<input type='url' name='jd_url' placeholder='https://…'>"
                "<label>…or paste the posting text</label>"
                "<textarea name='jd_text' class='tall'></textarea>"
                f"<p><button>Run {self._KINDS[kind].lower()}</button></p></form>"
                "<p class='hint'>This can take a few minutes — you'll get a "
                "live status page.</p></div>")
        self._send_html(page(self._KINDS[kind], user, body))

    def p_jobform(self, user, kind):
        if not self._profile(user):
            return self._redirect("/profile")
        jd_text = self._field("jd_text", "").strip()
        jd_url = self._field("jd_url", "").strip()
        if not jd_text and not jd_url:
            return self._send_html(page("Error", user,
                "<div class='card err'>Paste the posting or give a URL.</div>"), 400)
        label = self._field("label", "").strip() or kind
        job_id = jobs_mod.submit(DATA_DIR, user["username"], kind,
                                 jd_text, jd_url, label)
        self._redirect(f"/job/{job_id}")

    def r_job(self, job_id):
        user = self._need_login()
        if not user:
            return
        job = jobs_mod.get(re.sub(r"[^a-f0-9]", "", job_id), user["username"])
        if not job:
            return self._send_html(page("Not found", user,
                "<div class='card'><h1>Unknown job</h1></div>"), 404)
        label = h(job["label"])
        if job["status"] == "running":
            body = (f"<div class='card'><h1>{label}</h1>"
                    "<p><span class='pill'>working…</span></p>"
                    "<p class='hint'>The AI is working through the pipeline. "
                    "This page refreshes itself — keep it open.</p>"
                    "<meta http-equiv='refresh' content='4'></div>")
            return self._send_html(page(label, user, body))
        if job["status"] == "error":
            body = (f"<div class='card'><h1>{label}</h1>"
                    f"<p class='err'>Failed: {h(job['error'])}</p>"
                    "<p class='hint'>If the AI service was rate-limited, wait "
                    "and retry.</p><p><a class='btn' href='/app'>Back home</a></p>"
                    "</div>")
            return self._send_html(page(label, user, body))
        r = job["result"] or {}
        if job["kind"] == "eval":
            body = (f"<div class='card'><h1>{label} — fit report</h1>"
                    f"{render_mod.md_to_html(r.get('report',''))}"
                    "<p><a class='btn' href='/draft'>Draft for this posting →</a></p></div>")
        elif job["kind"] == "draft":
            slug = h(r.get("slug", ""))
            body = (f"<div class='card'><h1>{label} — drafts ready</h1>"
                    "<p class='ok'>✓ Passed the fabrication review.</p>"
                    "<p><a class='btn' href='/files/" + slug + "/cv.html'>Open CV</a> "
                    f"<a class='btn ghost' href='/files/{slug}/cover.html'>Open cover letter</a></p>"
                    "<p class='hint'>Open in your browser → Print → Save as PDF. "
                    "Review every line, then <b>you</b> submit it — nothing was sent anywhere.</p>"
                    f"<h2>Reviewer notes</h2>{render_mod.md_to_html(r.get('review',''))}</div>")
        else:
            body = (f"<div class='card'><h1>{label} — interview brief</h1>"
                    f"{render_mod.md_to_html(r.get('brief',''))}</div>")
        self._send_html(page(label, user, body))

    def r_files(self, rel):
        user = self._need_login()
        if not user:
            return
        base = os.path.realpath(os.path.join(self._user_root(user), "outputs"))
        target = os.path.realpath(os.path.join(base, rel))
        if not target.startswith(base + os.sep) or not os.path.isfile(target):
            return self._send_html(page("Not found", user,
                "<div class='card'><h1>404</h1></div>"), 404)
        ctype = "text/html; charset=utf-8" if target.endswith(".html") \
            else "text/plain; charset=utf-8"
        with open(target, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(data)

    # -- tracker -------------------------------------------------------
    def _tracker_rows(self, root):
        p = os.path.join(root, "tracker", "applications.csv")
        if not os.path.exists(p):
            return []
        with open(p, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def r_track(self):
        user = self._need_login()
        if not user:
            return
        root = self._user_root(user)
        rows = self._tracker_rows(root)
        tr = ""
        for r in rows:
            sel = "".join(
                f"<option{' selected' if s == r['status'] else ''}>{h(s)}</option>"
                for s in commands_mod.STATUSES)
            tr += (f"<tr><td>#{h(r['id'])}</td><td>{h(r['date'])}</td>"
                   f"<td>{h(r['role'])} @ {h(r['company'])}</td>"
                   f"<td><form method='post' action='/track/set' style='margin:0'>"
                   f"<input type='hidden' name='csrf' value='{h(_CSRF[user['username']])}'>"
                   f"<input type='hidden' name='id' value='{h(r['id'])}'>"
                   f"<select name='status'>{sel}</select> "
                   "<button class='btn ghost' style='padding:4px 10px'>Set</button>"
                   "</form></td></tr>")
        body = ("<div class='card'><h1>Application tracker</h1>" +
                (f"<table><tr><th></th><th>Date</th><th>Role</th><th>Status</th></tr>{tr}</table>"
                 if rows else "<p class='hint'>Nothing tracked yet.</p>") + "</div>"
                "<div class='card'><h2>Log an application</h2>"
                "<form method='post' action='/track/add'>"
                f"<input type='hidden' name='csrf' value='{h(_CSRF[user['username']])}'>"
                "<div class='row'><div><label>Company</label>"
                "<input type='text' name='company'></div>"
                "<div><label>Role</label><input type='text' name='role'></div></div>"
                "<label>Posting URL</label><input type='url' name='url'>"
                "<label>Notes</label><input type='text' name='notes'>"
                "<p><button>Track it</button></p></form></div>")
        self._send_html(page("Tracker", user, body))

    def p_track_add(self, user):
        ns = SimpleNamespace(action="add", company=self._field("company"),
                             role=self._field("role"), url=self._field("url"),
                             notes=self._field("notes"), id=None, status=None)
        commands_mod.cmd_track(ns, self._user_root(user))
        self._redirect("/track")

    def p_track_set(self, user):
        status = self._field("status")
        if status not in commands_mod.STATUSES:
            return self._redirect("/track")
        ns = SimpleNamespace(action="set", id=self._field("id"),
                             status=status, notes="",
                             company=None, role=None, url=None)
        try:
            commands_mod.cmd_track(ns, self._user_root(user))
        except SystemExit:
            pass
        self._redirect("/track")

    # -- password ------------------------------------------------------
    def r_password(self):
        user = self._need_login()
        if not user:
            return
        err = self._q.get("e", [""])[0]
        ok = self._q.get("ok", [""])[0]
        body = ("<div class='card'><h1>Change password</h1>"
                + (f"<p class='err'>{h(err)}</p>" if err else "")
                + (f"<p class='ok'>{h(ok)}</p>" if ok else "") +
                "<form method='post' action='/password'>"
                f"<input type='hidden' name='csrf' value='{h(_CSRF[user['username']])}'>"
                "<label>Current password</label>"
                "<input type='password' name='old' autocomplete='current-password'>"
                "<label>New password (min 8 chars)</label>"
                "<input type='password' name='new1' autocomplete='new-password'>"
                "<label>Repeat new password</label>"
                "<input type='password' name='new2' autocomplete='new-password'>"
                "<p><button>Change password</button></p></form></div>")
        self._send_html(page("Password", user, body))

    def p_password(self, user):
        if not self.server.auth.verify(user["username"], self._field("old")):
            return self._redirect("/password?e=" + urllib.parse.quote(
                "Current password is wrong."))
        n1, n2 = self._field("new1"), self._field("new2")
        if n1 != n2:
            return self._redirect("/password?e=" + urllib.parse.quote(
                "New passwords don't match."))
        try:
            self.server.auth.set_password(user["id"], n1)
        except ValueError as e:
            return self._redirect("/password?e=" + urllib.parse.quote(str(e)))
        self._redirect("/password?ok=" + urllib.parse.quote("Password changed."))

    # -- admin ---------------------------------------------------------
    def _need_admin(self):
        user = self._need_login()
        if user and not user.get("is_admin"):
            self._send_html(page("Denied", user,
                "<div class='card err'>Admins only.</div>"), 403)
            return None
        return user

    def r_admin(self):
        user = self._need_admin()
        if not user:
            return
        msg = self._q.get("m", [""])[0]
        rows = ""
        for u in self.server.auth.list_users():
            dis = "disabled" if u["disabled"] else "active"
            toggle = ("enable" if u["disabled"] else "disable")
            rows += (f"<tr><td>{h(u['username'])}</td>"
                     f"<td>{'admin' if u['is_admin'] else 'user'}</td>"
                     f"<td><span class='pill'>{dis}</span></td>"
                     f"<td><form method='post' action='/admin/toggle' style='display:inline;margin:0'>"
                     f"<input type='hidden' name='csrf' value='{h(_CSRF[user['username']])}'>"
                     f"<input type='hidden' name='id' value='{u['id']}'>"
                     f"<button class='btn ghost' style='padding:4px 10px'>{toggle}</button></form> "
                     f"<form method='post' action='/admin/resetpw' style='display:inline;margin:0'>"
                     f"<input type='hidden' name='csrf' value='{h(_CSRF[user['username']])}'>"
                     f"<input type='hidden' name='id' value='{u['id']}'>"
                     "<button class='btn ghost' style='padding:4px 10px'>reset password</button></form>"
                     "</td></tr>")
        body = ("<div class='card'><h1>Users</h1>"
                + (f"<p class='ok'>{h(msg)}</p>" if msg else "") +
                "<p class='hint'>Admins manage accounts only — nobody can read "
                "another user's profile, drafts, or tracker.</p>"
                f"<table><tr><th>Username</th><th>Role</th><th>Status</th><th></th></tr>{rows}</table></div>"
                "<div class='card'><h2>Add user</h2>"
                "<form method='post' action='/admin/add'>"
                f"<input type='hidden' name='csrf' value='{h(_CSRF[user['username']])}'>"
                "<div class='row'><div><label>Username</label>"
                "<input type='text' name='username'></div>"
                "<div><label>Password (blank = random)</label>"
                "<input type='text' name='password'></div></div>"
                "<p><label style='display:inline;font-weight:normal'>"
                "<input type='checkbox' name='is_admin' value='1' style='width:auto'> "
                "Make admin</label></p>"
                "<p><button>Create user</button></p></form></div>")
        self._send_html(page("Admin", user, body))

    def p_admin_add(self, user):
        if not user.get("is_admin"):
            return self._redirect("/app")
        uname = self._field("username", "").strip().lower()
        pw = self._field("password") or secrets.token_urlsafe(12)
        try:
            self.server.auth.create_user(uname, pw,
                                         self._field("is_admin") == "1")
        except ValueError as e:
            return self._redirect("/admin?m=" + urllib.parse.quote("Error: " + str(e)))
        msg = f"Created '{uname}' — password: {pw} (share it once, then forget it)"
        self._redirect("/admin?m=" + urllib.parse.quote(msg))

    def p_admin_toggle(self, user):
        if not user.get("is_admin"):
            return self._redirect("/app")
        try:
            uid = int(self._field("id"))
        except ValueError:
            return self._redirect("/admin")
        target = self.server.auth.get_user(uid)
        if target and target["username"] != user["username"]:
            self.server.auth.set_disabled(uid, not target["disabled"])
        self._redirect("/admin")

    def p_admin_resetpw(self, user):
        if not user.get("is_admin"):
            return self._redirect("/app")
        try:
            uid = int(self._field("id"))
        except ValueError:
            return self._redirect("/admin")
        target = self.server.auth.get_user(uid)
        if not target:
            return self._redirect("/admin")
        pw = secrets.token_urlsafe(12)
        self.server.auth.set_password(uid, pw)
        msg = f"New password for '{target['username']}': {pw} (share it once)"
        self._redirect("/admin?m=" + urllib.parse.quote(msg))


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, auth):
        self.auth = auth
        self.login_attempts = {}
        super().__init__(addr, Handler)


def ensure_dirs():
    users = os.path.join(DATA_DIR, "users")
    os.makedirs(users, exist_ok=True)
    os.chmod(users, 0o700)
    os.makedirs(DATA_DIR, exist_ok=True)


def cmd_serve(args):
    ensure_dirs()
    au = auth_mod.Auth(DATA_DIR)
    if au.user_count() == 0:
        admin_user = os.environ.get("DHRUV_APPLY_ADMIN_USER")
        admin_pass = os.environ.get("DHRUV_APPLY_ADMIN_PASS")
        if admin_user and admin_pass:
            au.create_user(admin_user, admin_pass, is_admin=True)
            print(f"bootstrap admin '{admin_user}' created")
        else:
            print("no users yet — create one with: python -m web.app adduser <name> --admin")
    port = args.port or PORT
    srv = Server(("0.0.0.0", port), au)
    print(f"dhruv-apply web on 0.0.0.0:{port}  (data: {DATA_DIR})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def _prompt_pw():
    pw = getpass.getpass("Password (min 8 chars): ")
    if len(pw) < 8:
        sys.exit("too short")
    if getpass.getpass("Repeat: ") != pw:
        sys.exit("mismatch")
    return pw


def cmd_adduser(args):
    ensure_dirs()
    au = auth_mod.Auth(DATA_DIR)
    pw = args.password or _prompt_pw()
    au.create_user(args.username, pw, is_admin=args.admin)
    print(f"user '{args.username.lower()}' created"
          + (" (admin)" if args.admin else ""))


def cmd_resetpw(args):
    ensure_dirs()
    au = auth_mod.Auth(DATA_DIR)
    row = au._db.execute("SELECT id FROM users WHERE username=?",
                         (args.username.strip().lower(),)).fetchone()
    if not row:
        sys.exit("no such user")
    pw = args.password or secrets.token_urlsafe(12)
    au.set_password(row["id"], pw)
    print(f"new password for '{args.username}': {pw}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m web.app")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the web server")
    s.add_argument("--port", type=int, default=None)
    a = sub.add_parser("adduser", help="create a user")
    a.add_argument("username")
    a.add_argument("--admin", action="store_true")
    a.add_argument("--password")
    r = sub.add_parser("resetpw", help="reset a user's password")
    r.add_argument("username")
    r.add_argument("--password")
    args = ap.parse_args(argv)
    {"serve": cmd_serve, "adduser": cmd_adduser,
     "resetpw": cmd_resetpw}[args.cmd](args)


if __name__ == "__main__":
    main()
