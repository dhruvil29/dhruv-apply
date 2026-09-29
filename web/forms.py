"""Human-friendly profile editing.

The profile JSON is nested; instead of a dynamic form builder, the web UI
edits it through simple text formats that are easy to type on a phone:

Experience (one block per role, blank line between):
    Senior Backend Engineer @ Northwind Labs | 2022-06 - present
    - Built REST APIs serving 2M requests/day
    - Cut p99 latency 40% with Redis caching

Education (one per line):
    B.Sc. Computer Science, Example University | 2018 - 2022
"""
import re


def profile_to_form(p):
    exp_blocks = []
    for e in p.get("experience", []):
        head = f"{e.get('role','')} @ {e.get('company','')} | {e.get('dates','')}"
        bullets = "\n".join("- " + b for b in e.get("bullets", []))
        exp_blocks.append(head + ("\n" + bullets if bullets else ""))
    edu_lines = [f"{e.get('degree','')}, {e.get('school','')} | {e.get('dates','')}"
                 for e in p.get("education", [])]
    return {
        "name": p.get("name", ""),
        "location": p.get("location", ""),
        "email": p.get("email", ""),
        "phone": p.get("phone", ""),
        "links": "\n".join(p.get("links", [])),
        "summary": p.get("summary", ""),
        "skills": ", ".join(p.get("skills", [])),
        "experience": "\n\n".join(exp_blocks),
        "education": "\n".join(edu_lines),
    }


def parse_experience(text):
    """Parse the block format above -> list of experience dicts."""
    out = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        lines = [l.rstrip() for l in block.strip().split("\n") if l.strip()]
        if not lines:
            continue
        m = re.match(r"^(.*?)\s*@\s*(.*?)\s*\|\s*(.*?)\s*$", lines[0])
        if not m:
            raise ValueError(f"bad role line (want 'Role @ Company | dates'): {lines[0]}")
        role, company, dates = (s.strip() for s in m.groups())
        bullets = []
        for l in lines[1:]:
            l = l.strip()
            if l.startswith(("-", "*")):
                l = l[1:].strip()
            if l:
                bullets.append(l)
        out.append({"role": role, "company": company, "dates": dates,
                    "bullets": bullets})
    return out


def parse_education(text):
    out = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(.*?),(.*?)\|\s*(.*?)\s*$", line)
        if not m:
            raise ValueError(f"bad education line (want 'Degree, School | dates'): {line}")
        degree, school, dates = (s.strip() for s in m.groups())
        out.append({"degree": degree, "school": school, "dates": dates})
    return out


def form_to_profile(fields, existing=None):
    """fields: flat dict of strings from the HTML form -> profile dict."""
    p = dict(existing or {})
    p["name"] = fields.get("name", "").strip()
    p["location"] = fields.get("location", "").strip()
    p["email"] = fields.get("email", "").strip()
    p["phone"] = fields.get("phone", "").strip()
    p["links"] = [l.strip() for l in fields.get("links", "").split("\n") if l.strip()]
    p["summary"] = fields.get("summary", "").strip()
    p["skills"] = [s.strip() for s in fields.get("skills", "").split(",") if s.strip()]
    p["experience"] = parse_experience(fields.get("experience", ""))
    p["education"] = parse_education(fields.get("education", ""))
    missing = [k for k in ("name", "email", "skills", "experience") if not p.get(k)]
    if missing:
        raise ValueError("missing required: " + ", ".join(missing))
    return p
