"""Background LLM jobs.

Draft/eval/interview each make several sequential LLM calls and can take
minutes — they run in worker threads while the browser polls /job/<id>.
Results are read back from the per-user output files the CLI already writes.
"""
import os
import re
import threading
import time
import traceback
import uuid
from types import SimpleNamespace

from apply import commands

_jobs = {}
_lock = threading.Lock()


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "job"


def _user_root(data_dir, username):
    root = os.path.join(data_dir, "users", username)
    os.makedirs(os.path.join(root, "profile"), exist_ok=True)
    os.makedirs(os.path.join(root, "outputs"), exist_ok=True)
    os.makedirs(os.path.join(root, "tracker"), exist_ok=True)
    os.makedirs(os.path.join(root, ".cache"), exist_ok=True)
    return root


def _write_jd(root, job_id, jd_text, jd_url):
    if jd_url and jd_url.strip().startswith(("http://", "https://")):
        return jd_url.strip()
    p = os.path.join(root, ".cache", f"jd-{job_id}.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(jd_text or "")
    return p


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def submit(data_dir, username, kind, jd_text, jd_url, label):
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "user": username, "kind": kind,
           "status": "running", "label": label or kind,
           "created": time.time(), "result": None, "error": None}
    with _lock:
        _jobs[job_id] = job
    t = threading.Thread(target=_run,
                         args=(data_dir, username, job_id, kind,
                               jd_text, jd_url, label),
                         daemon=True)
    t.start()
    return job_id


def get(job_id, username):
    with _lock:
        job = _jobs.get(job_id)
    if not job or job["user"] != username:
        return None
    return job


def _run(data_dir, username, job_id, kind, jd_text, jd_url, label):
    job = _jobs[job_id]
    try:
        root = _user_root(data_dir, username)
        jd_src = _write_jd(root, job_id, jd_text, jd_url)
        slug = _slug(label) + "-" + job_id[:6]
        if kind == "eval":
            # cmd_eval prepends "eval-" to args.out itself
            commands.cmd_eval(SimpleNamespace(jd=jd_src, out=slug), root)
            d = os.path.join(root, "outputs", "eval-" + slug)
            job["result"] = {"report": _read(os.path.join(d, "fit-report.md")),
                             "slug": "eval-" + slug}
        elif kind == "draft":
            commands.cmd_draft(SimpleNamespace(jd=jd_src, out=slug), root)
            d = os.path.join(root, "outputs", slug)
            job["result"] = {"slug": slug,
                             "cv": _read(os.path.join(d, "cv.md")),
                             "review": _read(os.path.join(d, "review.md"))}
        elif kind == "interview":
            commands.cmd_interview(SimpleNamespace(jd=jd_src, out=slug), root)
            d = os.path.join(root, "outputs", "interview-" + slug)
            job["result"] = {"brief": _read(os.path.join(d, "brief.md")),
                             "slug": "interview-" + slug}
        else:
            raise ValueError("unknown job kind")
        job["status"] = "done"
    except SystemExit as e:
        job["status"] = "error"
        job["error"] = str(e) or "the job stopped early"
    except Exception as e:  # noqa: BLE001 - surfaced to the user page
        job["status"] = "error"
        job["error"] = f"{type(e).__name__}: {e}"
        traceback.print_exc()


def recent(username, limit=10):
    with _lock:
        js = [j for j in _jobs.values() if j["user"] == username]
    js.sort(key=lambda j: j["created"], reverse=True)
    return js[:limit]
