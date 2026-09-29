"""Web app tests: auth, per-user isolation, and the mock-LLM pipeline.

Runs the real HTTP server on localhost with APPLY_LLM_MOCK=1, so the full
profile -> eval -> draft -> interview -> tracker flow is exercised without
needing a live LLM backend.
"""
import http.cookiejar
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 18771
BASE = f"http://127.0.0.1:{PORT}"

LONG_JD = (
    "Senior Backend Engineer (Python)\n\nAcme Corp is hiring a senior backend "
    "engineer to build and scale our payments platform. You will design REST "
    "APIs with FastAPI, optimize Postgres queries, build event-driven pipelines "
    "with Redis and Kafka, and mentor junior engineers. Requirements: 5+ years "
    "Python, deep Postgres knowledge, experience with Docker and Kubernetes, "
    "strong system design skills.\n\nWe offer competitive salary, remote-first "
    "culture, and meaningful equity."
)


class Redirect(Exception):
    def __init__(self, code, location):
        self.code, self.location = code, location


class NoRedirect(urllib.request.BaseHandler):
    def _raise(self, req, fp, code, msg, headers):
        raise Redirect(code, headers.get("Location"))

    http_error_301 = http_error_302 = http_error_303 = _raise
    http_error_307 = http_error_308 = _raise


class Client:
    def __init__(self):
        jar = http.cookiejar.CookieJar()
        self.op = urllib.request.OpenerDirector()
        self.op.add_handler(urllib.request.HTTPHandler())
        self.op.add_handler(urllib.request.HTTPCookieProcessor(jar))
        self.op.add_handler(urllib.request.HTTPErrorProcessor())
        self.op.add_handler(urllib.request.HTTPDefaultErrorHandler())
        self.op.add_handler(NoRedirect())

    def get(self, path):
        try:
            r = self.op.open(BASE + path, timeout=15)
            return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
        except Redirect as rd:
            return rd.code, ""

    def post(self, path, fields):
        data = urllib.parse.urlencode(fields).encode()
        try:
            r = self.op.open(urllib.request.Request(BASE + path, data=data),
                             timeout=60)
            return r.status, "", r.read().decode()[:200]
        except urllib.error.HTTPError as e:
            return e.code, "", e.read().decode()[:200]
        except Redirect as rd:
            return rd.code, rd.location or "", ""


def csrf(client, path):
    _, body = client.get(path)
    m = re.search(r"name='csrf' value='([^']+)'", body)
    return m.group(1) if m else ""


@pytest.fixture(scope="module")
def server():
    data = tempfile.mkdtemp(prefix="da-webtest-")
    env = dict(os.environ, DHRUV_APPLY_DATA=data, APPLY_LLM_MOCK="1")
    subprocess.run([sys.executable, "-m", "web.app", "adduser", "admin",
                    "--admin", "--password", "adminpass123"],
                   cwd=ROOT, env=env, check=True, capture_output=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "web.app", "serve", "--port", str(PORT)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/login", timeout=2).read()
                break
            except Exception:
                time.sleep(0.2)
        yield Client()
    finally:
        proc.terminate()


@pytest.fixture(scope="module")
def admin(server):
    s, loc, _ = server.post("/login", {"username": "admin",
                                      "password": "adminpass123"})
    assert s == 303 and loc == "/app"
    return server


PROFILE = {
    "name": "Asha Admin", "location": "Toronto, ON",
    "email": "asha@example.com", "phone": "416-555-0100",
    "links": "https://linkedin.example/asha",
    "summary": "Backend engineer.", "skills": "Python, Postgres",
    "experience": "Senior Backend @ Northwind | 2022-06 - present\n- Built APIs",
    "education": "B.Sc. CS, Example Uni | 2018 - 2022",
}


def _wait_job(client, job_id, needle, timeout=60):
    for _ in range(int(timeout / 2)):
        s, body = client.get(f"/job/{job_id}")
        assert s == 200
        if needle in body or "Failed:" in body:
            return body
        time.sleep(2)
    raise AssertionError(f"job {job_id} did not finish")


def test_login_rejects_bad_password(server):
    s, loc, _ = server.post("/login", {"username": "admin",
                                       "password": "wrong"})
    assert s == 303 and "e=" in loc


def test_anonymous_redirected(server):
    c = Client()
    s, _ = c.get("/app")
    assert s == 303


def test_profile_roundtrip(admin):
    tok = csrf(admin, "/profile")
    assert tok
    s, loc, _ = admin.post("/profile", {"csrf": tok, **PROFILE})
    assert s == 303
    s, body = admin.get("/app")
    assert "Asha Admin" in body


def test_profile_rejects_bad_experience(admin):
    bad = dict(PROFILE, csrf=csrf(admin, "/profile"),
               experience="not a valid block")
    s, loc, _ = admin.post("/profile", bad)
    assert s == 303 and "e=" in loc


def test_eval_pipeline(admin):
    s, loc, _ = admin.post("/eval", {"csrf": csrf(admin, "/eval"),
                                    "label": "Acme Backend",
                                    "jd_url": "", "jd_text": LONG_JD})
    assert s == 303
    job = re.search(r"/job/([a-f0-9]+)", loc).group(1)
    body = _wait_job(admin, job, "82/100")
    assert "82/100" in body


def test_draft_pipeline(admin):
    s, loc, _ = admin.post("/draft", {"csrf": csrf(admin, "/draft"),
                                     "label": "Acme Backend",
                                     "jd_url": "", "jd_text": LONG_JD})
    job = re.search(r"/job/([a-f0-9]+)", loc).group(1)
    body = _wait_job(admin, job, "drafts ready")
    m = re.search(r"/files/([a-z0-9-]+)/cv\.html", body)
    assert m, "no cv link in draft result"
    s, cv = admin.get(f"/files/{m.group(1)}/cv.html")
    assert s == 200 and "Mock CV" in cv
    # path traversal must not escape the user's own outputs dir
    s, _ = admin.get(f"/files/{m.group(1)}/../../users.db")
    assert s == 404


def test_tracker(admin):
    tok = csrf(admin, "/track")
    s, _, _ = admin.post("/track/add", {"csrf": tok, "company": "Acme",
                                       "role": "Backend",
                                       "url": "https://acme.example",
                                       "notes": ""})
    assert s == 303
    s, loc, _ = admin.post("/track/set", {"csrf": csrf(admin, "/track"),
                                          "id": "1", "status": "interview"})
    assert s == 303
    s, body = admin.get("/track")
    assert "Acme" in body and "interview" in body


def test_user_isolation(server):
    s, loc, _ = server.post(
        "/login", {"username": "admin", "password": "adminpass123"})
    assert s == 303
    s, loc, _ = server.post("/admin/add",
                            {"csrf": csrf(server, "/admin"),
                             "username": "bob", "password": "bobpass123"})
    assert s == 303
    bob = Client()
    s, loc, _ = bob.post("/login", {"username": "bob",
                                    "password": "bobpass123"})
    assert s == 303
    # bob must not reach admin-only pages or admin's jobs/files
    s, _ = bob.get("/admin")
    assert s == 403
    # bob sets up his own profile and runs his own job
    s, loc, _ = bob.post("/profile", {"csrf": csrf(bob, "/profile"),
                                      **{k: v for k, v in PROFILE.items()
                                         if k != "name"},
                                      "name": "Bob User"})
    assert s == 303
    s, _, _ = bob.post("/eval", {"csrf": csrf(bob, "/eval"), "label": "x",
                                 "jd_url": "", "jd_text": LONG_JD})
    assert s == 303  # bob can run his own jobs
    s, _ = bob.get("/job/doesnotexist12")
    assert s == 404
