"""MP Multiplayer login system - the bot side (no Discord code here, so it can be tested alone).

Accounts live only here (SQLite in DATA_DIR). Phones talk to us over public MQTT brokers, but every
frame is end-to-end encrypted:  ECDH P-256 (phone's one-time key x our AUTH_PRIVATE_KEY)
-> SHA-256("wagu-auth-v1" || shared || phone key) -> AES-256-GCM.  Passwords are stored as
PBKDF2-HMAC-SHA256 (200 000 rounds, random salt) and never leave this process.

A good login / sign up returns a ticket "WAGU1|user|discord|challenge|server|time" signed with our
key (ECDSA P-256, raw r||s). The game server checks it with the public key built into the mod.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization

TOPIC_REQ = "wagu/auth1/req"
TOPIC_RES = "wagu/auth1/res/"
CODE_ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 8
CODE_TTL = 10 * 60          # a /gen code works for 10 minutes
VERIFY_TTL = 20 * 60        # after /gen: 20 minutes to fill in the sign up form
SESSION_TTL = 12 * 3600     # logged in: new tickets (reconnect / host change) without the password
REMEMBER_TTL = 180 * 24 * 3600   # 3.21.9: saved login in the phone's account.txt (survives mod updates + bot restarts)
REMEMBER_MAX = 5                 # phones per account
MAX_ACCOUNTS = 3                 # 4.03: game accounts per Discord account (was 1)
DEVICE_TTL = 24 * 3600      # 3.21.8: a /gen is remembered for the phone 24 h (game restart -> Create your account)
DEV_RE = re.compile(r"^[0-9a-f]{32}$")
PBKDF2_ROUNDS = 200_000
USER_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
GENDERS = ("Male", "Female", "Other")


def _now():
    return int(time.time())


def _kv(text):
    out = {}
    for line in text.split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v
    return out


def _line(v, n):
    return re.sub(r"[\r\n]", "", str(v))[:n]


def _clean(v, n):
    return re.sub(r"[\r\n|=]", "", str(v))[:n]


class AuthCore:
    def __init__(self, private_hex, db_path):
        self.key = None
        if private_hex:
            d = int(private_hex.strip(), 16)
            self.key = ec.derive_private_key(d, ec.SECP256R1())
        self.lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS accounts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL, user_lc TEXT NOT NULL UNIQUE,
            discord_id TEXT NOT NULL, discord_name TEXT NOT NULL,
            pass_hash TEXT NOT NULL, salt TEXT NOT NULL, rounds INTEGER NOT NULL,
            gender TEXT NOT NULL, age INTEGER NOT NULL,
            created INTEGER NOT NULL, last_login INTEGER NOT NULL DEFAULT 0, logins INTEGER NOT NULL DEFAULT 0,
            last_server TEXT NOT NULL DEFAULT '')""")
        self._migrate_multi()
        self.db.execute("""CREATE TABLE IF NOT EXISTS remember(
            tok TEXT PRIMARY KEY, user_lc TEXT NOT NULL, dev TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS pending(
            dev TEXT PRIMARY KEY, discord_id TEXT NOT NULL, discord_name TEXT NOT NULL, expires INTEGER NOT NULL)""")
        self.db.commit()
        self.sessions = {}      # sid -> {key, broker, seen, code, vtoken, vdiscord, vname, vexp}
        self.codes = {}         # code -> (sid, expires)
        self.logins = {}        # sess token -> (user_lc, expires)
        self.avatar_q = []      # 3.24: (sid, discord_id, discord_name) for main.py to fetch
        self.avatar_cache = {}  # 3.24: discord_id -> (png bytes, expires)
        self.fails = {}         # key -> [timestamps]
        self.gen_rate = {}      # discord id -> [timestamps]

    def _migrate_multi(self):
        """4.03: up to MAX_ACCOUNTS game accounts per Discord. Old databases have discord_id UNIQUE:
        rebuild the table once without it (same columns, same rows)."""
        row = self.db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()
        if not row or "discord_id TEXT NOT NULL UNIQUE" not in row[0]:
            return
        new_sql = row[0].replace("discord_id TEXT NOT NULL UNIQUE", "discord_id TEXT NOT NULL").replace("CREATE TABLE accounts", "CREATE TABLE accounts_new", 1)
        self.db.execute("BEGIN")
        self.db.execute(new_sql)
        self.db.execute("INSERT INTO accounts_new SELECT * FROM accounts")
        self.db.execute("DROP TABLE accounts")
        self.db.execute("ALTER TABLE accounts_new RENAME TO accounts")
        self.db.commit()

    # ---------------------------------------------------------------- crypto
    @property
    def ready(self):
        return self.key is not None

    def public_hex(self):
        return self.key.public_key().public_bytes(serialization.Encoding.X962,
                                                  serialization.PublicFormat.UncompressedPoint).hex()

    def _session_for(self, pub, broker):
        sid = hashlib.sha256(pub).hexdigest()[:16]
        s = self.sessions.get(sid)
        if s is None:
            peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), pub)
            z = self.key.exchange(ec.ECDH(), peer)
            k = hashlib.sha256(b"wagu-auth-v1" + z + pub).digest()
            s = {"key": k, "sid": sid}
            self.sessions[sid] = s
        s["broker"] = broker
        s["seen"] = _now()
        return s

    # ---------------------------------------------------------------- 3.24: Discord avatar
    AVATAR_CHUNK = 280          # every value is cut at 300 characters by seal()

    def avatar_answer(self, png, dname):
        b64 = base64.b64encode(png).decode()
        parts = [b64[i:i + self.AVATAR_CHUNK] for i in range(0, len(b64), self.AVATAR_CHUNK)]
        out = {"op": "avatar", "rid": "a", "ok": 1, "n": len(parts), "dname": _clean(dname, 40)}
        for i, p in enumerate(parts):
            out[f"p{i}"] = p
        return out

    def take_avatar_jobs(self):
        with self.lock:
            jobs, self.avatar_q = self.avatar_q, []
        return jobs

    def avatar_done(self, sid, discord_id, dname, png):
        """main.py got the picture (png=None: failed). -> encrypted push for that phone, or None."""
        with self.lock:
            s = self.sessions.get(sid)
            if png:
                self.avatar_cache[str(discord_id)] = (png, _now() + 3600)
            if not s:
                return None
            ans = self.avatar_answer(png, dname) if png else {"op": "avatar", "rid": "a", "ok": 0, "err": "no avatar"}
            return self.seal(s, ans)

    def seal(self, s, fields):
        plain = "\n".join(f"{k}={_line(v, 300)}" for k, v in fields.items()).encode()
        iv = secrets.token_bytes(12)
        return bytes([1]) + iv + AESGCM(s["key"]).encrypt(iv, plain, b"WS")

    def sign_ticket(self, user, discord_id, chal, server):
        payload = f"WAGU1|{user}|{discord_id}|{chal}|{_clean(server, 39)}|{_now()}"
        der = self.key.sign(payload.encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return payload, (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex()

    def sign_status(self, text):
        """3.21.7: signs the MP Railway status beacon. Own prefix, so it can never pass as a login ticket
        (the game server only accepts payloads that start with "WAGU1|")."""
        payload = "WAGUSTATUS1|" + text
        der = self.key.sign(payload.encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex()

    def account_count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]

    # ---------------------------------------------------------------- housekeeping
    def _expire(self):
        t = _now()
        for c in [c for c, (_, e) in self.codes.items() if e < t]:
            del self.codes[c]
        for k in [k for k, (_, e) in self.logins.items() if e < t]:
            del self.logins[k]
        for sid in [sid for sid, s in self.sessions.items() if s["seen"] < t - 3600 and s.get("vexp", 0) < t]:
            del self.sessions[sid]

    def _rate(self, table, key, limit, window):
        t = time.time()
        lst = [x for x in table.get(key, []) if x > t - window]
        table[key] = lst
        if len(lst) >= limit:
            return False
        lst.append(t)
        return True

    def _account(self, where, arg):
        cur = self.db.execute(f"SELECT user,discord_id,discord_name,pass_hash,salt,rounds,gender,age,created,last_login,logins,last_server FROM accounts WHERE {where}=?", (arg,))
        row = cur.fetchone()
        if not row:
            return None
        keys = ("user", "discord_id", "discord_name", "pass_hash", "salt", "rounds", "gender", "age", "created", "last_login", "logins", "last_server")
        return dict(zip(keys, row))

    def account_by_discord(self, discord_id):
        """The most recently used game account of this Discord (None = none)."""
        with self.lock:
            a = self.accounts_by_discord(discord_id)
            return a[0] if a else None

    def _accounts_of(self, discord_id):
        rows = self.db.execute("SELECT user_lc FROM accounts WHERE discord_id=? ORDER BY last_login DESC, created DESC", (str(discord_id),)).fetchall()
        return [self._account("user_lc", r[0]) for r in rows]

    def accounts_by_discord(self, discord_id):
        """4.03: every game account of this Discord (max MAX_ACCOUNTS), last used first."""
        with self.lock:
            return self._accounts_of(discord_id)

    def account_of(self, discord_id, user):
        """4.03: one account by name, only when it belongs to this Discord."""
        with self.lock:
            a = self._account("user_lc", (user or "").lower())
            return a if a and a["discord_id"] == str(discord_id) else None

    def _set_password(self, user_lc, pw):
        """3.56: forgot password. New hash + salt; every saved login (all phones) stops working."""
        salt = secrets.token_hex(16)
        self.db.execute("UPDATE accounts SET pass_hash=?, salt=?, rounds=? WHERE user_lc=?",
                        (self._hash(pw, salt, PBKDF2_ROUNDS), salt, PBKDF2_ROUNDS, user_lc))
        self.db.execute("DELETE FROM remember WHERE user_lc=?", (user_lc,))
        self.db.commit()
        for k in [k for k, (u, _) in self.logins.items() if u == user_lc]:
            del self.logins[k]

    def reset_by_discord(self, discord_id, pw, user=""):
        """Discord /resetpass: (ok, message). 4.03: user = which of the (max 3) accounts."""
        with self.lock:
            if not (6 <= len(pw) <= 32):
                return False, "Password: 6-32 characters."
            if not self._rate(self.fails, "dreset:" + str(discord_id), 5, 3600):
                return False, "Too many resets. Wait an hour."
            al = self._accounts_of(discord_id)
            if not al:
                return False, "This Discord has no game account yet. Create one in the game (Login screen > New account)."
            a = next((x for x in al if x["user"].lower() == (user or "").strip().lower()), None) if user else (al[0] if len(al) == 1 else None)
            if not a:
                return False, "This Discord has %d game accounts (%s): type the username of the one to reset." % (len(al), ", ".join(x["user"] for x in al))
            self._set_password(a["user"].lower(), pw)
            return True, a["user"]

    def _hash(self, password, salt, rounds):
        return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), rounds).hex()

    @staticmethod
    def _tok_key(tok):
        return hashlib.sha256(b"wagu-remember1|" + tok.encode()).hexdigest()

    def _remember(self, user_lc, s):
        """3.21.9: a login token the phone keeps in account.txt; bound to its auth_device id."""
        if not s or not s.get("dev"):
            return None
        tok, dk, t = secrets.token_hex(16), self._dev_key(s["dev"]), _now()
        self.db.execute("DELETE FROM remember WHERE user_lc=? AND dev=?", (user_lc, dk))
        self.db.execute("INSERT INTO remember(tok,user_lc,dev,created,expires) VALUES(?,?,?,?,?)",
                        (self._tok_key(tok), user_lc, dk, t, t + REMEMBER_TTL))
        old = self.db.execute("SELECT tok FROM remember WHERE user_lc=? ORDER BY created DESC LIMIT -1 OFFSET ?",
                              (user_lc, REMEMBER_MAX)).fetchall()
        for (k,) in old:
            self.db.execute("DELETE FROM remember WHERE tok=?", (k,))
        self.db.execute("DELETE FROM remember WHERE expires<?", (t,))
        self.db.commit()
        return tok

    def _remembered(self, tok, s):
        """user_lc of a saved login, or None. Sliding: every use gives it 180 more days."""
        if not re.fullmatch(r"[0-9a-f]{32}", tok or "") or not s or not s.get("dev"):
            return None
        row = self.db.execute("SELECT user_lc,dev,expires FROM remember WHERE tok=?", (self._tok_key(tok),)).fetchone()
        if not row or row[2] < _now() or not hmac.compare_digest(row[1], self._dev_key(s["dev"])):
            return None
        self.db.execute("UPDATE remember SET expires=? WHERE tok=?", (_now() + REMEMBER_TTL, self._tok_key(tok)))
        self.db.commit()
        return row[0]

    def _logged_in(self, a, chal, server, sid, s=None):
        self.db.execute("UPDATE accounts SET last_login=?, logins=logins+1, last_server=? WHERE user_lc=?",
                        (_now(), _clean(server, 39), a["user"].lower()))
        self.db.commit()
        sess = self._remember(a["user"].lower(), s)
        if not sess:                                     # old phone (no device id): 12 h in memory, like before
            sess = secrets.token_hex(16)
            self.logins[sess] = (a["user"].lower(), _now() + SESSION_TTL)
        out = {"ok": 1, "user": a["user"], "sess": sess}
        if re.fullmatch(r"[0-9a-f]{32}", chal or ""):
            out["ticket"], out["sig"] = self.sign_ticket(a["user"], a["discord_id"], chal, server)
        return out

    # ---------------------------------------------------------------- phone requests
    def handle_frame(self, frame, broker=0):
        """One encrypted request from a phone -> (sid, encrypted answer) or None."""
        if not self.ready or len(frame) < 1 + 65 + 12 + 16 or frame[0] != 1:
            return None
        pub, iv, ct = frame[1:66], frame[66:78], frame[78:]
        with self.lock:
            self._expire()
            try:
                s = self._session_for(pub, broker)
                req = _kv(AESGCM(s["key"]).decrypt(iv, ct, b"WC").decode("utf-8", "replace"))
            except Exception:
                return None
            ans = self._handle(s, req)
            ans["rid"] = req.get("rid", "")
            ans.setdefault("op", req.get("op", ""))
            return s["sid"], self.seal(s, ans)

    def _pending_verified(self, s):
        """3.21.7: the "verified" push from /gen, while the phone hasn't used it yet."""
        p = s.get("vpush")
        if p and s.get("vtoken") and s.get("vpush_until", 0) > _now():
            return dict(p)
        return None

    def repush(self):
        """3.21.7: re-send "verified" every few seconds. Android pauses the game while you are in
        Discord, so its MQTT link is down at the moment of /gen and the first push is lost."""
        out = []
        with self.lock:
            for sid, s in list(self.sessions.items()):
                p = self._pending_verified(s)
                if p:
                    out.append((sid, self.seal(s, p)))
                elif s.get("vpush"):
                    s["vpush"] = None
        return out

    # ---------------------------------------------------------------- 3.21.8: verified phones
    @staticmethod
    def _dev_key(dev):
        return hashlib.sha256(b"wagu-dev1|" + dev.encode()).hexdigest()

    def _remember_dev(self, s):
        if s.get("dev") and s.get("vdiscord"):
            self.db.execute("INSERT OR REPLACE INTO pending(dev,discord_id,discord_name,expires) VALUES(?,?,?,?)",
                            (self._dev_key(s["dev"]), s["vdiscord"], s["vname"], _now() + DEVICE_TTL))
            self.db.commit()

    def _forget_dev(self, s=None, discord_id=None):
        if s is not None and s.get("dev"):
            self.db.execute("DELETE FROM pending WHERE dev=?", (self._dev_key(s["dev"]),))
        if discord_id:
            self.db.execute("DELETE FROM pending WHERE discord_id=?", (str(discord_id),))
        self.db.execute("DELETE FROM pending WHERE expires<?", (_now(),))
        self.db.commit()

    def _restore_dev(self, s):
        """A phone that did /gen and then restarted the game (new key = new session): verified again."""
        if not s.get("dev") or s.get("vtoken"):
            return None
        row = self.db.execute("SELECT discord_id,discord_name,expires FROM pending WHERE dev=?", (self._dev_key(s["dev"]),)).fetchone()
        if not row or row[2] < _now():
            return None
        al = self._accounts_of(row[0])
        a = al[0] if len(al) >= MAX_ACCOUNTS else None   # 4.03: room for another account = Sign up
        s["vtoken"] = secrets.token_hex(16)
        s["vdiscord"], s["vname"] = row[0], row[1]
        s["vexp"] = _now() + VERIFY_TTL
        push = {"op": "verified", "vtoken": s["vtoken"], "dname": row[1], "has": 1 if a else 0, "user": a["user"] if a else (al[0]["user"] if al else ""),
                "count": len(al), "max": MAX_ACCOUNTS, "users": ",".join(x["user"] for x in al)}
        s["vpush"], s["vpush_until"] = push, _now() + 10 * 60
        if a:
            self._forget_dev(s)                      # has an account already: just the Login screen once
        return dict(push)

    def _handle(self, s, q):
        op = q.get("op")
        sid = s["sid"]
        dev = q.get("dev", "")
        if DEV_RE.match(dev):
            s["dev"] = dev
        if op not in ("hello", "gen", "stats", "avatar"):
            s["vpush"] = None                            # the phone moved on (sign up / login): stop re-sending
        if op in ("hello", "gen"):
            p = self._pending_verified(s) or self._restore_dev(s)
            if p:
                return p                                 # back from Discord (or game restarted): tell it right away
        if op == "hello":
            return {"ok": 1}
        if op == "gen":
            code = q.get("code", "").upper()
            if len(code) != CODE_LEN or any(c not in CODE_ALPHA for c in code):
                return {"ok": 0, "err": "bad code"}
            other = self.codes.get(code)
            if other and other[0] != sid:
                return {"ok": 0, "err": "dup"}           # the phone picks a new random code
            if not self._rate(self.fails, "gen:" + sid, 20, 600):
                return {"ok": 0, "err": "Too many codes. Wait a few minutes."}
            for c in [c for c, (x, _) in self.codes.items() if x == sid]:
                del self.codes[c]                        # one live code per screen
            self.codes[code] = (sid, _now() + CODE_TTL)
            s["code"] = code
            return {"ok": 1, "ttl": CODE_TTL}
        if op == "signup":
            if not s.get("vtoken") or not hmac.compare_digest(s["vtoken"], q.get("vtoken", "")) or s.get("vexp", 0) < _now():
                return {"ok": 0, "err": "Verification expired. Get a new code."}
            user, pw = q.get("user", ""), q.get("pass", "")
            gender, age = q.get("gender", ""), q.get("age", "")
            if not USER_RE.match(user):
                return {"ok": 0, "err": "Username: 3-20 letters, numbers or _"}
            if not (6 <= len(pw) <= 32):
                return {"ok": 0, "err": "Password: 6-32 characters"}
            if gender not in GENDERS:
                return {"ok": 0, "err": "Pick a gender"}
            if not age.isdigit() or not (10 <= int(age) <= 99):
                return {"ok": 0, "err": "Age: 10-99"}
            al = self._accounts_of(s["vdiscord"])
            if len(al) >= MAX_ACCOUNTS:   # 4.03: max 3 game accounts per Discord (was 1)
                return {"ok": 0, "err": "This Discord already has %d game accounts (the limit): %s. Log in." % (len(al), ", ".join(x["user"] for x in al))}
            if self._account("user_lc", user.lower()):
                return {"ok": 0, "err": "That username is taken"}
            salt = secrets.token_hex(16)
            self.db.execute("INSERT INTO accounts(user,user_lc,discord_id,discord_name,pass_hash,salt,rounds,gender,age,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (user, user.lower(), s["vdiscord"], s["vname"], self._hash(pw, salt, PBKDF2_ROUNDS), salt, PBKDF2_ROUNDS, gender, int(age), _now()))
            self.db.commit()
            s["vtoken"] = None
            self._forget_dev(s, s["vdiscord"])
            a = self._account("user_lc", user.lower())
            return self._logged_in(a, q.get("chal", ""), q.get("srv", ""), sid, s)
        if op == "reset":                                # 3.56: forgot password (after a fresh /gen)
            if not s.get("vtoken") or not hmac.compare_digest(s["vtoken"], q.get("vtoken", "")) or s.get("vexp", 0) < _now():
                return {"ok": 0, "again": 1, "err": "Verification expired. Do /gen with the new code."}
            pw = q.get("pass", "")
            if not (6 <= len(pw) <= 32):
                return {"ok": 0, "err": "Password: 6-32 characters"}
            if not self._rate(self.fails, "reset:" + s["vdiscord"], 5, 3600):
                return {"ok": 0, "err": "Too many resets. Wait an hour."}
            al = self._accounts_of(s["vdiscord"])
            if not al:
                return {"ok": 0, "err": "This Discord has no game account yet. Create one."}
            want = q.get("user", "").strip().lower()   # 4.03: which account (max 3 per Discord)
            a = next((x for x in al if x["user"].lower() == want), None) if want else al[0]
            if not a:
                return {"ok": 0, "err": "That username is not one of this Discord's accounts: " + ", ".join(x["user"] for x in al)}
            self._set_password(a["user"].lower(), pw)
            s["vtoken"] = None
            self._forget_dev(s, s["vdiscord"])
            return self._logged_in(a, q.get("chal", ""), q.get("srv", ""), sid, s)
        if op == "login":
            user, pw = q.get("user", ""), q.get("pass", "")
            if not self._rate(self.fails, "login:" + sid, 10, 600) or not self._rate(self.fails, "user:" + user.lower(), 8, 600):
                return {"ok": 0, "err": "Too many tries. Wait 10 minutes."}
            a = self._account("user_lc", user.lower())
            if not a or not hmac.compare_digest(a["pass_hash"], self._hash(pw, a["salt"], a["rounds"])):
                return {"ok": 0, "err": "Wrong username or password"}
            return self._logged_in(a, q.get("chal", ""), q.get("srv", ""), sid, s)
        if op in ("ticket", "stats", "avatar"):
            v = self.logins.get(q.get("sess", ""))
            if not v or v[1] < _now():
                u = self._remembered(q.get("sess", ""), s)      # 3.21.9: saved login (account.txt)
                v = (u, _now() + SESSION_TTL) if u else None
                if v and op == "ticket":   # checked against the phone id every time (not cached)
                    self.db.execute("UPDATE accounts SET last_login=?, logins=logins+1, last_server=? WHERE user_lc=?",
                                                    (_now(), _clean(q.get("srv", ""), 39), u))
                    self.db.commit()
            if not v or v[1] < _now():
                return {"ok": 0, "err": "Session expired. Log in again.", "relogin": 1}
            a = self._account("user_lc", v[0])
            if not a:
                return {"ok": 0, "err": "Account not found", "relogin": 1}
            if op == "ticket":
                if not re.fullmatch(r"[0-9a-f]{32}", q.get("chal", "")):
                    return {"ok": 0, "err": "bad challenge"}
                t, sig = self.sign_ticket(a["user"], a["discord_id"], q["chal"], q.get("srv", ""))
                return {"ok": 1, "user": a["user"], "ticket": t, "sig": sig}
            if op == "avatar":   # 3.24: launcher profile picture; main.py fetches it from Discord, then pushes it
                hit = self.avatar_cache.get(str(a["discord_id"]))
                if hit and hit[1] > _now():
                    return self.avatar_answer(hit[0], a["discord_name"])
                self.avatar_q.append((sid, str(a["discord_id"]), a["discord_name"]))
                return {"ok": 1, "wait": 1}
            return {"ok": 1, "user": a["user"], "discord": a["discord_name"], "gender": a["gender"], "age": a["age"],
                    "created": a["created"], "logins": a["logins"], "last": a["last_login"], "server": a["last_server"]}
        return {"ok": 0, "err": "unknown request"}

    # ---------------------------------------------------------------- Discord /gen
    def gen(self, discord_id, discord_name, code):
        """/gen CODE in #verification. Returns (reply text, [(sid, encrypted push)])."""
        code = (code or "").strip().upper().replace(" ", "").replace("-", "")
        with self.lock:
            self._expire()
            if not self.ready:
                return "Verification is not set up yet (the bot has no AUTH_PRIVATE_KEY).", []
            if not self._rate(self.gen_rate, str(discord_id), 6, 600):
                return "Too many /gen. Wait a few minutes.", []
            hit = self.codes.pop(code, None)
            if not hit:
                return "That code is wrong or expired. Look at the code in the game (it changes every time) and try again.", []
            sid = hit[0]
            s = self.sessions.get(sid)
            if not s:
                return "The game screen for that code is gone. Open it again in the game for a new code.", []
            s["vtoken"] = secrets.token_hex(16)
            s["vdiscord"], s["vname"] = str(discord_id), _clean(discord_name, 40)
            s["vexp"] = _now() + VERIFY_TTL
            al = self._accounts_of(discord_id)
            a = al[0] if len(al) >= MAX_ACCOUNTS else None   # 4.03: full = Login, else Sign up (another account)
            push = {"op": "verified", "vtoken": s["vtoken"], "dname": s["vname"], "has": 1 if a else 0, "user": a["user"] if a else (al[0]["user"] if al else ""),
                    "count": len(al), "max": MAX_ACCOUNTS, "users": ",".join(x["user"] for x in al)}
            s["vpush"], s["vpush_until"] = push, _now() + 10 * 60
            if not a:
                self._remember_dev(s)
            names = ", ".join(f"**{x['user']}**" for x in al)
            if a:
                text = f"Verified. This Discord already has {len(al)}/{MAX_ACCOUNTS} game accounts ({names}): log in with one of them in the game."
            elif al:
                text = f"Verified. You have {len(al)}/{MAX_ACCOUNTS} game accounts ({names}). Go back to the game to create another one, or tap Login to use one."
            else:
                text = "Verified. Go back to the game and create your account."
            return text, [(sid, self.seal(s, push))]

    def broker_of(self, sid):
        s = self.sessions.get(sid)
        return s.get("broker", 0) if s else 0
