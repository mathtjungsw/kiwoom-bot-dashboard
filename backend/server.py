"""Password-protected saved-data API, served only through the TLS reverse proxy."""
import argparse
import collections
import contextlib
import getpass
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import threading
import time
from .reader import Reader, number

WEEK = 7 * 86400
HERE = Path(__file__).resolve().parent.parent


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ":" + hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,expires INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS attempts(peer TEXT NOT NULL,ts INTEGER NOT NULL); CREATE INDEX IF NOT EXISTS attempts_time ON attempts(ts);")
        self.path.chmod(0o600)

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=3)
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialized(self):
        with self.db() as db:
            return db.execute("SELECT 1 FROM settings WHERE key='password'").fetchone() is not None

    def setup(self, password):
        if not 12 <= len(password) <= 128:
            raise ValueError("Use a password of 12 to 128 characters")
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('password',?)", (password_hash(password),))
            db.execute("DELETE FROM sessions")

    def login(self, password, peer):
        now = int(time.time())
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM attempts WHERE ts<?", (now-900,))
            count = db.execute("SELECT count(*) FROM attempts WHERE peer=?", (peer,)).fetchone()[0]
            total = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
            if count >= 8 or total >= 100:
                return None, "rate"
            db.execute("INSERT INTO attempts VALUES (?,?)", (peer, now))
            row = db.execute("SELECT value FROM settings WHERE key='password'").fetchone()
        if not row:
            return None, "setup"
        salt = row[0].split(":")[0]
        if not hmac.compare_digest(password_hash(password, salt), row[0]):
            return None, "password"
        token = secrets.token_urlsafe(32)
        expires = now + WEEK
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE expires<=?", (now,))
            if db.execute("SELECT count(*) FROM sessions").fetchone()[0] >= 50:
                db.execute("DELETE FROM sessions WHERE hash IN (SELECT hash FROM sessions ORDER BY expires LIMIT 1)")
            db.execute("INSERT INTO sessions VALUES (?,?)", (digest(token), expires))
            db.execute("DELETE FROM attempts WHERE peer=?", (peer,))
        return dict(token=token, expires_at=expires), None

    def valid(self, token):
        if len(token) > 100:
            return False
        with self.db() as db:
            row = db.execute("SELECT expires FROM sessions WHERE hash=?", (digest(token),)).fetchone()
        return bool(row and row[0] > time.time())

    def logout(self, token):
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE hash=?", (digest(token),))

    def capital(self):
        with self.db() as db:
            values = dict(db.execute("SELECT key,value FROM settings WHERE key IN ('initial_capital','net_external_flows')"))
        return {key:number(value) for key,value in values.items()}

    def set_capital(self, initial, net_external_flows=0):
        initial = number(initial, True)
        flows = number(net_external_flows)
        if initial is None or flows is None:
            raise ValueError("Capital must be positive and external flows must be finite")
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('initial_capital',?)", (str(initial),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('net_external_flows',?)", (str(flows),))


class Application:
    def __init__(self, data, root, control, origins, service_check=None):
        self.store = Store(data)
        self.reader = Reader(root)
        self.control = Path(control)
        self.origins = origins
        self.lock = threading.Lock()
        self.cache = None
        self.cache_at = 0
        self.service_check = service_check or self.active

    @staticmethod
    def active():
        return subprocess.run(["systemctl", "is-active", "--quiet", "kiwoom-stock"], timeout=2, check=False).returncode == 0

    def snapshot(self):
        with self.lock:
            if self.cache is None or time.monotonic()-self.cache_at >= 2:
                self.cache = self.reader.snapshot(self.service_check(), capital=self.store.capital())
                self.cache_at = time.monotonic()
            return self.cache

    def pause(self):
        with self.lock:
            saved=json.loads((self.reader.root / "trail_state.json").read_text(encoding="utf-8"))
            if not isinstance(saved.get("dashboard_control",{}).get("paused"),bool):
                raise ValueError("봇의 웹 제어 연결을 먼저 완료해야 합니다.")
            command = {"id": secrets.token_hex(16), "paused": True}
            self.control.parent.mkdir(parents=True, exist_ok=True)
            temp = self.control.with_suffix(".tmp")
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(command, handle)
                handle.flush()
                os.fsync(handle.fileno())
            temp.chmod(0o600)
            temp.replace(self.control)
            return command


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass  # Never log passwords, tokens or financial data.

        def reply(self, status, data):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            origin = self.headers.get("Origin")
            if origin in app.origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.reply(200 if self.headers.get("Origin") in app.origins else 403, {})

        def token(self):
            auth = self.headers.get("Authorization", "")
            return auth[7:] if auth.startswith("Bearer ") else ""

        def do_GET(self):
            if self.path == "/bot-api/health":
                return self.reply(200, {"ok": True})
            if not app.store.valid(self.token()):
                return self.reply(401, {"error": "로그인이 필요합니다."})
            if self.path != "/bot-api/snapshot":
                return self.reply(404, {"error": "Not found"})
            try:
                self.reply(200, app.snapshot())
            except Exception as exc:
                print("Snapshot unavailable: " + type(exc).__name__, flush=True)
                self.reply(503, {"error": "서버 자료 확인이 지연되었습니다."})

        def do_POST(self):
            if self.headers.get("Origin") not in app.origins:
                self.close_connection = True
                return self.reply(403, {"error": "허용되지 않은 요청입니다."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2048 or self.headers.get("Transfer-Encoding") or not self.headers.get("Content-Type", "").startswith("application/json"):
                    self.close_connection = True
                    return self.reply(400, {"error": "Invalid request"})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError()
            except (ValueError, UnicodeError):
                return self.reply(400, {"error": "Invalid JSON"})
            if self.path == "/bot-api/login":
                password = data.get("password")
                if not isinstance(password, str) or not 1 <= len(password) <= 128:
                    return self.reply(400, {"error": "비밀번호를 확인하세요."})
                # Only the trusted loopback reverse proxy can supply this header.
                peer = digest(self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip())
                result, error = app.store.login(password, peer)
                if error:
                    messages = {"rate":"시도가 많습니다. 15분 뒤 다시 시도하세요.", "setup":"서버에서 최초 비밀번호 설정이 필요합니다.", "password":"비밀번호를 확인하세요."}
                    return self.reply(429 if error == "rate" else 401, {"error": messages[error]})
                return self.reply(200, result)
            token = self.token()
            if not app.store.valid(token):
                return self.reply(401, {"error": "로그인이 필요합니다."})
            if self.path == "/bot-api/logout":
                app.store.logout(token)
                return self.reply(200, {"ok": True})
            if self.path == "/bot-api/control" and data == {"action": "pause"}:
                try:
                    command=app.pause()
                except (ValueError,OSError):
                    return self.reply(409, {"error":"봇의 웹 제어 연결을 확인하지 못했습니다. 서버 확인 후 다시 시도하세요."})
                return self.reply(200, {"ok": True, "id": command["id"]})
            self.reply(404, {"error": "지원하지 않는 요청입니다."})
    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16
    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(*args, **kwargs)
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise
    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["serve", "password", "capital"], nargs="?", default="serve")
    parser.add_argument("--initial-capital", type=float)
    parser.add_argument("--net-external-flows", type=float, default=0)
    parser.add_argument("--data", default=os.getenv("DASHBOARD_AUTH_DB", "/var/lib/kiwoom-dashboard/auth.db"))
    parser.add_argument("--root", default="/opt/bots/kiwoom-stock")
    parser.add_argument("--control", default="/var/lib/kiwoom-dashboard-control/command.json")
    parser.add_argument("--port", type=int, default=8880)
    args = parser.parse_args()
    if args.action == "capital":
        Store(args.data).set_capital(args.initial_capital, args.net_external_flows)
        print("Capital settings saved. Authentication and bot data unchanged.")
        return
    if args.action == "password":
        first = getpass.getpass("New dashboard password (12-128 characters): ")
        second = getpass.getpass("Confirm password: ")
        if first != second:
            raise SystemExit("Passwords do not match")
        Store(args.data).setup(first)
        print("Password saved. All previous sessions invalidated.")
        return
    origins = os.getenv("DASHBOARD_ORIGINS", "https://mathtjungsw.github.io,https://stock-journal.52-79-211-161.sslip.io").split(",")
    app = Application(args.data, args.root, args.control, origins)
    print("Dashboard API listening on loopback", flush=True)
    Server(("127.0.0.1", args.port), handler(app)).serve_forever()


if __name__ == "__main__":
    main()
