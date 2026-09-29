"""Workflow commands: setup, eval, draft, interview, track."""
import csv
import datetime
import json
import os
import re

from . import jd as jd_mod
from . import llm
from . import profile as profile_mod
from . import render

STATUSES = ["applied", "screening", "interview", "offer", "rejected",
            "withdrawn", "ghosted"]


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "job"


def _out_dir(root, slug):
    d = os.path.join(root, "outputs", slug)
    os.makedirs(d, exist_ok=True)
    return d


def cmd_setup(args, root):
    if args.from_resume:
        with open(args.from_resume, encoding="utf-8") as f:
            resume_text = f.read()
        print("Parsing resume with the LLM...")
        resp = llm.chat([
            {"role": "system", "content": llm.system_prompt("setup.md")},
            {"role": "user", "content": "RESUME TEXT:\n" + resume_text[:8000] +
             "\n\nOutput ONLY the JSON profile, no commentary."}])
        m = re.search(r"\{.*\}", resp, re.S)
        if not m:
            raise SystemExit("Could not parse a profile from the resume. "
                             "Try the interactive setup instead.")
        data = json.loads(m.group(0))
    else:
        print("Building your master profile. Be specific; this is the "
              "ground truth every draft is checked against.\n")
        data = {
            "name": input("Full name: ").strip(),
            "location": input("Location (City, ST): ").strip(),
            "email": input("Email: ").strip(),
            "phone": input("Phone: ").strip(),
            "links": [l for l in
                      input("Links (LinkedIn, GitHub, portfolio — comma separated): ")
                      .split(",") if l.strip()],
            "summary": input("Professional summary (2-3 sentences): ").strip(),
            "skills": [s.strip() for s in
                       input("Skills (comma separated): ").split(",") if s.strip()],
            "experience": [],
            "education": [],
        }
        print("\nExperience — enter roles one by one (blank role finishes):")
        while True:
            role = input("\nRole title: ").strip()
            if not role:
                break
            exp = {
                "role": role,
                "company": input("Company: ").strip(),
                "dates": input("Dates (e.g. 2022-06 – present): ").strip(),
                "bullets": [],
            }
            print("Achievement bullets (blank line finishes; quantify impact):")
            while True:
                b = input("- ").strip()
                if not b:
                    break
                exp["bullets"].append(b)
            data["experience"].append(exp)
        print("\nEducation (blank degree finishes):")
        while True:
            deg = input("Degree: ").strip()
            if not deg:
                break
            data["education"].append({
                "degree": deg,
                "school": input("School: ").strip(),
                "dates": input("Dates: ").strip(),
            })
    profile_mod.save(root, data)
    print("\nReview profile/profile.json, then run: python -m apply eval --jd <url-or-file>")


def cmd_eval(args, root):
    prof = profile_mod.load(root)
    jd_text = jd_mod.load_jd(args.jd)
    print("Evaluating fit...")
    report = llm.chat([
        {"role": "system", "content": llm.system_prompt("evaluate.md")},
        {"role": "user", "content": "MASTER PROFILE:\n" +
         profile_mod.to_text(prof) + "\n\nJOB DESCRIPTION:\n" + jd_text}])
    slug = _slug(args.out or jd_text.split("\n")[0])
    d = _out_dir(root, "eval-" + slug)
    with open(os.path.join(d, "fit-report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    with open(os.path.join(d, "jd.txt"), "w", encoding="utf-8") as f:
        f.write(jd_text)
    print(report)
    print(f"\nSaved to {d}/")


def _revise_cv(draft, issues, prof_text, jd_text):
    return llm.chat([
        {"role": "system", "content": llm.system_prompt("drafter.md") +
         "\n\nYou are now REVISING. Fix every issue below. Do not "
         "reintroduce rejected claims."},
        {"role": "user", "content": "MASTER PROFILE:\n" + prof_text +
         "\n\nJOB DESCRIPTION:\n" + jd_text +
         "\n\nDRAFT CV:\n" + draft +
         "\n\nREVIEWER ISSUES (fix all):\n" + issues +
         "\n\nOutput the revised CV only."}])


def cmd_draft(args, root):
    prof = profile_mod.load(root)
    prof_text = profile_mod.to_text(prof)
    jd_text = jd_mod.load_jd(args.jd)

    print("1/4 drafting CV...")
    draft = llm.chat([
        {"role": "system", "content": llm.system_prompt("drafter.md")},
        {"role": "user", "content": "MASTER PROFILE:\n" + prof_text +
         "\n\nJOB DESCRIPTION:\n" + jd_text}])

    print("2/4 reviewer checking for fabrication...")
    review = llm.chat([
        {"role": "system", "content": llm.system_prompt("reviewer.md")},
        {"role": "user", "content": "MASTER PROFILE:\n" + prof_text +
         "\n\nJOB DESCRIPTION:\n" + jd_text + "\n\nDRAFT CV:\n" + draft}],
        temperature=0.1)

    final_cv = draft
    if review.lstrip().upper().startswith("## FAIL"):
        print("3/4 reviewer found issues — revising...")
        final_cv = _revise_cv(draft, review, prof_text, jd_text)
    else:
        print("3/4 reviewer passed.")

    print("4/4 drafting cover letter...")
    cover = llm.chat([
        {"role": "system", "content": llm.system_prompt("cover_drafter.md")},
        {"role": "user", "content": "MASTER PROFILE:\n" + prof_text +
         "\n\nJOB DESCRIPTION:\n" + jd_text}])

    slug = _slug(args.out or jd_text.split("\n")[0])
    d = _out_dir(root, slug)
    files = {
        "jd.txt": jd_text,
        "cv.md": final_cv,
        "cv.html": render.render_page("CV - " + prof["name"], final_cv),
        "cover.md": cover,
        "cover.html": render.render_page("Cover letter - " + prof["name"], cover),
        "review.md": review,
    }
    for name, content in files.items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(content)
    print(f"\nDone. Review BEFORE submitting:\n  {d}/cv.html\n  {d}/cover.html")
    print("Open in a browser -> Print -> Save as PDF. Nothing was submitted anywhere.")


def cmd_interview(args, root):
    prof = profile_mod.load(root)
    jd_text = jd_mod.load_jd(args.jd)
    print("Preparing interview brief...")
    brief = llm.chat([
        {"role": "system", "content": llm.system_prompt("interview.md")},
        {"role": "user", "content": "MASTER PROFILE:\n" +
         profile_mod.to_text(prof) + "\n\nJOB DESCRIPTION:\n" + jd_text}],
        max_tokens=3000)
    slug = _slug(args.out or jd_text.split("\n")[0])
    d = _out_dir(root, "interview-" + slug)
    with open(os.path.join(d, "brief.md"), "w", encoding="utf-8") as f:
        f.write(brief)
    print(brief)
    print(f"\nSaved to {d}/brief.md")


def _tracker_path(root):
    return os.path.join(root, "tracker", "applications.csv")


def _read_tracker(root):
    p = _tracker_path(root)
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cmd_track(args, root):
    os.makedirs(os.path.join(root, "tracker"), exist_ok=True)
    if args.action == "add":
        rows = _read_tracker(root)
        nid = str(max([int(r["id"]) for r in rows] + [0]) + 1)
        row = {"id": nid,
               "date": datetime.date.today().isoformat(),
               "company": args.company or "",
               "role": args.role or "",
               "url": args.url or "",
               "status": "applied",
               "notes": args.notes or ""}
        new_file = not rows
        with open(_tracker_path(root), "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=row.keys())
            if new_file:
                w.writeheader()
            w.writerow(row)
        print(f"Tracked #{nid}: {row['role']} @ {row['company']}")
    elif args.action == "list":
        rows = _read_tracker(root)
        if not rows:
            print("No applications tracked yet.")
            return
        filt = (args.status or "").lower()
        for r in rows:
            if filt and r["status"] != filt:
                continue
            print(f"#{r['id']} {r['date']} [{r['status']}] {r['role']} @ {r['company']}")
    elif args.action == "set":
        if args.status not in STATUSES:
            raise SystemExit(f"status must be one of: {', '.join(STATUSES)}")
        rows = _read_tracker(root)
        found = False
        for r in rows:
            if r["id"] == str(args.id):
                r["status"] = args.status
                if args.notes:
                    r["notes"] = args.notes
                found = True
        if not found:
            raise SystemExit(f"No application #{args.id}")
        with open(_tracker_path(root), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
        print(f"#{args.id} -> {args.status}")
