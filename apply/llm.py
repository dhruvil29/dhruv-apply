"""Minimal OpenAI-compatible chat client (stdlib only, no pip installs).

Config via env vars:
  APPLY_LLM_BASE_URL  default https://132-145-97-183.sslip.io/v1
  APPLY_LLM_MODEL     default gemini-3.1-flash-lite
  APPLY_LLM_API_KEY   bearer key; falls back to ~/.config/gateway-dispatch/api_key
"""
import json
import os
import urllib.request
import urllib.error

_DRY_RUN = False


def set_dry_run(value=True):
    global _DRY_RUN
    _DRY_RUN = value


def config():
    base = os.environ.get("APPLY_LLM_BASE_URL",
                          "https://132-145-97-183.sslip.io/v1").rstrip("/")
    model = os.environ.get("APPLY_LLM_MODEL", "gemini-3.1-flash-lite")
    key = os.environ.get("APPLY_LLM_API_KEY", "")
    if not key:
        try:
            with open(os.path.expanduser("~/.config/gateway-dispatch/api_key"),
                      encoding="utf-8") as f:
                key = f.read().strip()
        except OSError:
            pass
    return base, model, key


def chat(messages, max_tokens=2500, temperature=0.3, timeout=180):
    """Send chat-completions request, return the assistant's text."""
    if _DRY_RUN:
        return "[dry-run] LLM call skipped. Prompt preview:\n" + \
               messages[-1]["content"][:400]
    if os.environ.get("APPLY_LLM_MOCK") == "1":
        # Test-only: canned pipeline outputs, no network. Used to verify
        # the full web/CLI flow while the gateway is rate-limited.
        # Matched against prompts/*.md headers.
        sys0 = messages[0]["content"] if messages[0]["role"] == "system" else ""
        if "# Job-fit evaluation" in sys0:
            return ("## VERDICT: Pursue\n## Fit score: 82/100\n\n"
                    "## Requirement-by-requirement\n- Python APIs: strong match\n"
                    "## Gaps\n- Go: not in profile\n## Risks\n- none material")
        if "# CV reviewer" in sys0:
            return "## PASS\nNo fabrication found."
        if "# Cover-letter drafter" in sys0:
            return ("Dear Hiring Manager,\n\nI am excited to apply... "
                    "[mock cover letter]\n\nSincerely,\nCandidate")
        if "# Interview prep" in sys0:
            return ("# Interview brief\n\n## Likely questions\n1. Tell me about "
                    "yourself [mock]\n## Questions to ask them\n1. Team shape?")
        return "# Mock CV\n\n## Summary\nMock candidate summary.\n\n## Skills\n- Python\n\n_"
    base, model, key = config()
    payload = {"model": model, "messages": messages,
               "max_tokens": max_tokens, "temperature": temperature}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(base + "/chat/completions",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"LLM request failed: HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM request failed: {e.reason}")
    return data["choices"][0]["message"]["content"].strip()


def system_prompt(name):
    with open(os.path.join(os.path.dirname(__file__), "..", "prompts",
                           name), encoding="utf-8") as f:
        return f.read()


def ping():
    return chat([{"role": "user",
                  "content": "Reply with exactly: OK"}], max_tokens=10)
