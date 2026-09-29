"""Privacy guard: personal data must never be git-tracked.

Fails CI if profile.json, outputs/, tracker/applications.csv or .env
would be committed. Only the example profile may be tracked.
"""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SENSITIVE = [
    "profile/profile.json",
    "outputs",
    "tracker/applications.csv",
    ".env",
]


def _ignored(path):
    r = subprocess.run(["git", "check-ignore", "-q", path],
                       cwd=ROOT, capture_output=True)
    return r.returncode == 0


def test_sensitive_paths_are_ignored():
    for p in SENSITIVE:
        assert _ignored(p), f"{p} is NOT git-ignored — personal data could leak!"


def test_example_profile_is_tracked_not_real_one():
    example = os.path.join(ROOT, "profile", "profile.example.json")
    assert os.path.exists(example)
    assert not _ignored("profile/profile.example.json"), \
        "example profile must be committable"
    assert not os.path.exists(os.path.join(ROOT, "profile", "profile.json")), \
        "a real profile.json exists in the working tree — keep it out of git"
