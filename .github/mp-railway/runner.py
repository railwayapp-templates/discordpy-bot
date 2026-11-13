"""MP Railway cloud runner (3.21.7): keeps the bot online from GitHub Actions, no server needed.

One workflow run = one ~5 h 40 min shift. The runner
  * restores accounts.db (AES-256-GCM encrypted with a key derived from AUTH_PRIVATE_KEY) from the
    "mp-railway-data" branch, so accounts survive between shifts,
  * starts main.py and restarts it if it crashes,
  * saves the encrypted database back to that branch every 2 minutes when it changed,
  * auto deploys: a new commit on main is pulled and the bot restarted within 2 minutes,
  * near the end of the shift starts the next run (workflow_dispatch) and hands over.
"""
import base64, hashlib, os, signal, sqlite3, subprocess, sys, tempfile, time, json, urllib.request

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = os.getcwd()
DATA_DIR = os.path.join(ROOT, "data")
DB = os.path.join(DATA_DIR, "accounts.db")
BRANCH = "mp-railway-data"
SHIFT = int(os.environ.get("SHIFT_SECONDS", str(5 * 3600 + 40 * 60)))
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
KEY = hashlib.sha256(b"WAGU-DB1|" + os.environ.get("AUTH_PRIVATE_KEY", "").strip().lower().encode()).digest()
started = time.time()
stop = False


def log(*a):
    print("[mp-railway]", *a, flush=True)


def sh(*cmd, check=True, cwd=None):
    r = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(cmd[:3])}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


# ------------------------------------------------------------------ encrypted DB on a branch
def restore():
    os.makedirs(DATA_DIR, exist_ok=True)
    if sh("git", "ls-remote", "--heads", "origin", BRANCH, check=False) == "":
        log("no saved database yet (first run)")
        return
    sh("git", "fetch", "-q", "--depth", "1", "origin", BRANCH)
    blob = subprocess.run(["git", "show", f"FETCH_HEAD:accounts.db.enc"], capture_output=True).stdout
    if not blob:
        return
    raw = base64.b64decode(blob)
    plain = AESGCM(KEY).decrypt(raw[:12], raw[12:], b"accounts.db")
    with open(DB, "wb") as f:
        f.write(plain)
    log(f"restored accounts.db ({len(plain)} bytes)")


last_hash = None


def save(reason):
    global last_hash
    if not os.path.exists(DB):
        return
    tmp = tempfile.mktemp(suffix=".db")
    try:
        src = sqlite3.connect(DB, timeout=10)
        dst = sqlite3.connect(tmp)
        src.backup(dst); dst.close(); src.close()   # consistent copy while the bot writes
        plain = open(tmp, "rb").read()
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    h = hashlib.sha256(plain).hexdigest()
    if h == last_hash:
        return
    nonce = os.urandom(12)
    enc = base64.b64encode(nonce + AESGCM(KEY).encrypt(nonce, plain, b"accounts.db"))
    wt = tempfile.mkdtemp()
    try:
        sh("git", "init", "-q", wt)
        with open(os.path.join(wt, "accounts.db.enc"), "wb") as f:
            f.write(enc)
        with open(os.path.join(wt, "README.md"), "w") as f:
            f.write("MP Railway cloud runner data: accounts.db, AES-256-GCM encrypted (key from AUTH_PRIVATE_KEY). Do not edit.\n")
        sh("git", "-C", wt, "add", "-A")
        sh("git", "-C", wt, "-c", "user.name=mp-railway", "-c", "user.email=mp-railway@users.noreply.github.com",
           "commit", "-q", "-m", f"accounts.db ({reason})")
        url = f"https://x-access-token:{TOKEN}@github.com/{REPO}.git"
        sh("git", "-C", wt, "push", "-q", "-f", url, f"HEAD:refs/heads/{BRANCH}")   # one commit, stays small
        last_hash = h
        log(f"saved accounts.db ({reason})")
    except Exception as e:
        log("save failed:", e)
    finally:
        subprocess.run(["rm", "-rf", wt])


# ------------------------------------------------------------------ bot process
bot = None


def start_bot():
    global bot
    env = dict(os.environ, DATA_DIR=DATA_DIR, MP_RAILWAY_APP="discordpy-bot",
               MP_RAILWAY_HOST="MP Railway (cloud runner)",
               MP_RAILWAY_COMMIT=sh("git", "rev-parse", "HEAD"), PYTHONUNBUFFERED="1")
    bot = subprocess.Popen([sys.executable, "main.py"], cwd=ROOT, env=env)
    log("bot started, pid", bot.pid)


def stop_bot():
    if bot and bot.poll() is None:
        bot.send_signal(signal.SIGINT)
        try:
            bot.wait(15)
        except subprocess.TimeoutExpired:
            bot.kill()


def new_commit():
    try:
        remote = sh("git", "ls-remote", "origin", "refs/heads/main").split()[0]
    except Exception:
        return False
    if remote and remote != sh("git", "rev-parse", "HEAD"):
        log("new commit", remote[:7], "- deploying")
        sh("git", "fetch", "-q", "--depth", "1", "origin", "main")
        sh("git", "reset", "-q", "--hard", "FETCH_HEAD")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"])
        return True
    return False


def dispatch_next():
    """Start the next shift (it waits in the queue until this one ends: same concurrency group)."""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/actions/workflows/mp-railway-cloud.yml/dispatches",
            data=json.dumps({"ref": "main"}).encode(), method="POST",
            headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"})
        urllib.request.urlopen(req, timeout=20)
        log("next shift queued")
        return True
    except Exception as e:
        log("could not queue the next shift:", e)
        return False


def on_signal(*_):
    global stop
    stop = True


signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGINT, on_signal)

restore()
start_bot()
queued = False
last_check = time.time()
while not stop and time.time() - started < SHIFT:
    time.sleep(5)
    if bot.poll() is not None:
        log("bot exited with", bot.returncode, "- restarting in 5 s")
        time.sleep(5)
        start_bot()
    if time.time() - last_check >= 120:
        last_check = time.time()
        save("periodic")
        if new_commit():
            stop_bot(); start_bot()
    if not queued and time.time() - started > SHIFT - 600:
        queued = dispatch_next()

log("shift over" if not stop else "stopping (cancelled)")
stop_bot()
save("end of shift")
if not queued and not stop:
    dispatch_next()
