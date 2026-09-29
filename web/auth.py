"""User accounts and sessions. Stdlib only.

- Passwords: PBKDF2-HMAC-SHA256, 200k iterations, per-user salt.
- Sessions: 256-bit random tokens, stored as SHA-256 hashes, 24h expiry.
- Users can only ever touch their own data; admins manage accounts
  (create/disable/reset password) but cannot read user data.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time

SESSION_TTL = 24 * 3600
_ITER = 200_000
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    pw_salt BLOB NOT NULL,
    pw_hash BLOB NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    disabled INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
    token_hash BLOB PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created INTEGER NOT NULL,
    expires INTEGER NOT NULL,
    csrf TEXT NOT NULL);
"""


def valid_username(name):
    return bool(_USERNAME_RE.match(name or ""))


def _hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITER)


class Auth:
    def __init__(self, data_dir):
        os.makedirs(data_dir, exist_ok=True)
        self.db_path = os.path.join(data_dir, "users.db")
        fresh = not os.path.exists(self.db_path)
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        if fresh:
            os.chmod(self.db_path, 0o600)

    # -- users ---------------------------------------------------------
    def user_count(self):
        return self._db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create_user(self, username, password, is_admin=False):
        username = (username or "").strip().lower()
        if not valid_username(username):
            raise ValueError("username must be 3-32 chars: a-z, 0-9, _ or -")
        if not password or len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        salt = secrets.token_bytes(32)
        try:
            cur = self._db.execute(
                "INSERT INTO users(username,pw_salt,pw_hash,is_admin,disabled,created)"
                " VALUES(?,?,?,?,?,?)",
                (username, salt, _hash_pw(password, salt),
                 1 if is_admin else 0, 0, int(time.time())))
            self._db.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError(f"user '{username}' already exists")

    def verify(self, username, password):
        row = self._db.execute(
            "SELECT * FROM users WHERE username=?",
            ((username or "").strip().lower(),)).fetchone()
        if not row or row["disabled"]:
            return None
        expect = _hash_pw(password or "", row["pw_salt"])
        if hmac.compare_digest(expect, row["pw_hash"]):
            return dict(row)
        return None

    def get_user(self, user_id):
        row = self._db.execute("SELECT * FROM users WHERE id=?",
                               (user_id,)).fetchone()
        return dict(row) if row else None

    def list_users(self):
        return [dict(r) for r in self._db.execute(
            "SELECT id,username,is_admin,disabled,created FROM users ORDER BY username")]

    def set_password(self, user_id, password):
        if not password or len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        salt = secrets.token_bytes(32)
        self._db.execute("UPDATE users SET pw_salt=?,pw_hash=? WHERE id=?",
                         (salt, _hash_pw(password, salt), user_id))
        self._db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        self._db.commit()

    def set_disabled(self, user_id, disabled):
        self._db.execute("UPDATE users SET disabled=? WHERE id=?",
                         (1 if disabled else 0, user_id))
        if disabled:
            self._db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        self._db.commit()

    # -- sessions ------------------------------------------------------
    def make_session(self, user_id):
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        now = int(time.time())
        th = hashlib.sha256(token.encode()).digest()
        self._db.execute(
            "INSERT INTO sessions(token_hash,user_id,created,expires,csrf)"
            " VALUES(?,?,?,?,?)", (th, user_id, now, now + SESSION_TTL, csrf))
        # prune expired
        self._db.execute("DELETE FROM sessions WHERE expires<?", (now,))
        self._db.commit()
        return token, csrf

    def get_session(self, token):
        if not token:
            return None
        th = hashlib.sha256(token.encode()).digest()
        row = self._db.execute(
            "SELECT s.csrf, s.expires, u.* FROM sessions s JOIN users u"
            " ON u.id=s.user_id WHERE s.token_hash=?", (th,)).fetchone()
        if not row or row["expires"] < time.time() or row["disabled"]:
            return None
        user = dict(row)
        return user

    def destroy_session(self, token):
        if token:
            th = hashlib.sha256(token.encode()).digest()
            self._db.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
            self._db.commit()

    def csrf_for_token(self, token):
        if not token:
            return ""
        th = hashlib.sha256(token.encode()).digest()
        row = self._db.execute(
            "SELECT csrf FROM sessions WHERE token_hash=?", (th,)).fetchone()
        return row["csrf"] if row else ""
