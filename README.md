# dhruv-apply

**The viral AI job-search workflow, rebuilt free-forever.**

`dhruv-apply` is a local-first AI job-application assistant. It organises your
career profile, evaluates job postings against it, drafts a tailored CV and
cover letter per role (drafter → reviewer → revise, with a fabrication guard),
preps you for interviews, and tracks every application.

It **never applies for you**. You review every claim and submit manually.
Treat all output as a draft.

## Why this exists

The workflow that inspired this project —
[MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search)
(44k stars, the author got hired with it) — is excellent but requires paid
Claude Code. `dhruv-apply` ports the proven pipeline to any OpenAI-compatible
LLM endpoint, so it runs **free**: a self-hosted gateway or local Ollama.
Patterns also borrowed from [Gsync/jobsync](https://github.com/Gsync/jobsync)
(full-loop tracking) and [srbhr/Resume-Matcher](https://github.com/srbhr/Resume-Matcher)
(tailoring module). See [CREDITS](#credits).

## Quick start

Requirements: Python 3.10+, nothing else (`pip install` not needed).

```bash
git clone https://github.com/dhruvil29/dhruv-apply.git
cd dhruv-apply

# 1. Build your master profile (interactive, ~5 minutes)
python -m apply setup
#    or parse an existing resume:  python -m apply setup --from-resume resume.txt

# 2. Evaluate a posting
python -m apply eval --jd https://example.com/jobs/123
python -m apply eval --jd posting.txt        # or a local file

# 3. Draft a tailored CV + cover letter (drafter -> reviewer -> revise)
python -m apply draft --jd https://example.com/jobs/123 --out outputs/acme-backend

# 4. Open outputs/acme-backend/cv.html and cover.html in a browser, Print -> Save as PDF

# 5. Track it
python -m apply track add --company "Acme" --role "Backend Engineer" --url https://example.com/jobs/123
python -m apply track list
python -m apply track set --id 1 --status interview

# 6. Prep for the interview
python -m apply interview --jd https://example.com/jobs/123
```

## How it works

```
setup            eval                 draft <jd>                    interview
  |                |                     |                            |
  v                v                     v                            v
Master         Fit score 0-100      CV drafter -> reviewer ->    Likely questions
profile.json   strengths/gaps       revise (fabrication guard)   + STAR bullets
  |            verdict: apply?       Cover letter drafter         grounded in
  v                |                 -> cv.md/cv.html             YOUR profile
Local only,    JD kept in           cover.md/cover.html
never          outputs/             You review, you submit
committed
```

**Pipeline rules (enforced by prompts, not just docs):**
- The reviewer rejects any claim not grounded in your profile. No invented
  experience, no inflated titles, no fake metrics.
- The tool never submits applications, sends emails, or fills web forms.
- Your profile and outputs live in git-ignored folders. A privacy test
  (`tests/test_privacy.py`) fails CI if personal data is ever tracked.

## Configuration

Any OpenAI-compatible chat-completions endpoint works. Set env vars
(or create a `.env` file — it is git-ignored):

| Variable | Default | Purpose |
|---|---|---|
| `APPLY_LLM_BASE_URL` | `https://132-145-97-183.sslip.io/v1` | LLM endpoint |
| `APPLY_LLM_MODEL` | `gemini-3.5-flash-lite` | Model ID |
| `APPLY_LLM_API_KEY` | _(empty)_ | Bearer key, if the endpoint needs one |

Ollama (fully offline) example:

```bash
export APPLY_LLM_BASE_URL=http://localhost:11434/v1
export APPLY_LLM_MODEL=qwen3:8b
python -m apply eval --jd posting.txt
```

> Note: free gateway tiers can hit rate limits (HTTP 429). The tool surfaces
> the gateway's own error; wait for the reset window or point
> `APPLY_LLM_BASE_URL` at Ollama to keep working offline.

`--dry-run` runs any command without calling the LLM (verifies plumbing).

## Privacy

- `profile/profile.json`, `outputs/`, `tracker/applications.csv`, `.env` are
  git-ignored. Only `profile/profile.example.json` (fake data) is tracked.
- Do not fork publicly with real data in it. Clone privately instead.
- Job postings are treated as untrusted input (prompt-injection defence is
  part of the reviewer prompt).

## Tests

```bash
python -m pytest tests/ -q
```

## Credits

- Pipeline concept, fit criteria, and drafter→reviewer discipline:
  [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search) (MIT)
- Full-loop tracking idea: [Gsync/jobsync](https://github.com/Gsync/jobsync) (MIT)
- Tailoring-module thinking: [srbhr/Resume-Matcher](https://github.com/srbhr/Resume-Matcher) (Apache-2.0)

## License

MIT — see [LICENSE](LICENSE).
