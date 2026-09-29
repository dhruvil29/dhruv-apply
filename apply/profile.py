"""Master career profile: load, validate, present."""
import json
import os

REQUIRED = ["name", "email", "skills", "experience"]


def path(root):
    return os.path.join(root, "profile", "profile.json")


def load(root):
    p = path(root)
    if not os.path.exists(p):
        raise SystemExit("No profile found. Run: python -m apply setup")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        raise SystemExit("profile.json is missing: " + ", ".join(missing) +
                         ". Run: python -m apply setup")
    return data


def save(root, data):
    p = path(root)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.chmod(p, 0o600)
    print(f"Saved {p} (mode 600, git-ignored)")


def to_text(profile):
    return json.dumps(profile, indent=2, ensure_ascii=False)
