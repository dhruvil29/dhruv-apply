"""dhruv-apply CLI: free-forever AI job-application assistant."""
import argparse
import os
import sys

from . import commands, llm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m apply",
        description="Local-first AI job-application assistant. Never applies for you.")
    ap.add_argument("--dry-run", action="store_true",
                    help="run without calling the LLM")
    ap.add_argument("--ping", action="store_true",
                    help="test the LLM connection and exit")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("setup", help="build your master career profile")
    s.add_argument("--from-resume", metavar="FILE",
                   help="parse an existing resume instead of the interview")

    e = sub.add_parser("eval", help="score your fit for a job posting")
    e.add_argument("--jd", required=True, help="job posting URL or text file")
    e.add_argument("--out", help="output folder name")

    d = sub.add_parser("draft",
                       help="draft tailored CV + cover letter (reviewed, never sent)")
    d.add_argument("--jd", required=True, help="job posting URL or text file")
    d.add_argument("--out", help="output folder name")

    i = sub.add_parser("interview", help="interview prep brief for a posting")
    i.add_argument("--jd", required=True, help="job posting URL or text file")
    i.add_argument("--out", help="output folder name")

    t = sub.add_parser("track", help="application tracker")
    t.add_argument("action", choices=["add", "list", "set"])
    t.add_argument("--company"); t.add_argument("--role"); t.add_argument("--url")
    t.add_argument("--notes"); t.add_argument("--id"); t.add_argument("--status")

    args = ap.parse_args(argv)
    if args.dry_run:
        llm.set_dry_run(True)
    if args.ping:
        print("LLM says:", llm.ping())
        return 0
    if not args.cmd:
        ap.print_help()
        return 1
    {"setup": commands.cmd_setup,
     "eval": commands.cmd_eval,
     "draft": commands.cmd_draft,
     "interview": commands.cmd_interview,
     "track": commands.cmd_track}[args.cmd](args, ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
