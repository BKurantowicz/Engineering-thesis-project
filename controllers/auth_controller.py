"""Shared accounts and revocable desktop sessions, independent of warehouse files."""
from contextlib import closing, contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3
import uuid


runtime = None
_maintenance = ContextVar('warehouse_maintenance', default=False)


@contextmanager
def maintenance():
    """Explicit offline fixture/maintenance scope, unavailable in an app session."""
    if runtime is not None:
        raise AuthError('auth_forbidden')
    token = _maintenance.set(True)
    try:
        yield
    finally:
        _maintenance.reset(token)


def ensure_session():
    if runtime is not None:
        return runtime.require()
    if not _maintenance.get():
        raise AuthError('auth_required')


def bind(controller):
    controller._session_epoch = runtime.epoch if runtime else None


def can_admin():
    if runtime is None:
        return _maintenance.get()
    try:
        return runtime.require()['role'] == 'admin'
    except AuthError:
        return False


class AuthError(ValueError):
    pass


def require_access(controller=None, admin=False):
    """Recheck a bound operation, including checkpoints in background workers."""
    ensure_session()
    if runtime is not None:
        runtime.require(admin)
        if getattr(controller, '_session_epoch', runtime.epoch) != runtime.epoch:
            raise AuthError('auth_required')
        if runtime.warehouse and hasattr(controller, 'db_path') and str(Path(controller.db_path).resolve()) != runtime.warehouse:
            raise AuthError('warehouse_context_changed')


def authorized(admin=False):
    """Require a session at business entry points; offline fixtures opt in explicitly."""
    def decorate(method):
        @wraps(method)
        def call(*args, **kwargs):
            require_access(args[0] if args else None, admin)
            return method(*args, **kwargs)
        return call
    return decorate


def actor():
    return ensure_session()


class AuthController:
    def __init__(self, path):
        self.path = str(Path(path).resolve())
        self.session = None
        self.epoch = 0
        self.warehouse = None
        with closing(self.connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS accounts(
                user_id TEXT PRIMARY KEY, login TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','employee')),
                must_change INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1)""")
            db.execute("CREATE TABLE IF NOT EXISTS warehouses(path TEXT PRIMARY KEY)")
            db.execute("CREATE TABLE IF NOT EXISTS app_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)")

    def active_warehouse(self):
        self.require()
        with closing(self.connect()) as db:
            row = db.execute("SELECT value FROM app_state WHERE key='warehouse'").fetchone()
            return row[0] if row else None

    def remember_warehouse(self, path):
        self.require()
        with closing(self.connect()) as db, db:
            if not db.execute('SELECT 1 FROM warehouses WHERE path=?',(path,)).fetchone():
                raise AuthError('warehouse_unregistered')
            db.execute("INSERT INTO app_state(key,value) VALUES('warehouse',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(path,))

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def hash_password(password):
        if not isinstance(password, str) or not password or len(password) > 1024:
            raise AuthError("auth_password_invalid")
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
        return f"pbkdf2_sha256$600000${salt}${digest}"

    @staticmethod
    def matches(password, encoded):
        try:
            algorithm, rounds, salt, expected = encoded.split('$')
            if algorithm != 'pbkdf2_sha256' or int(rounds) != 600000:
                return False
            actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
            return hmac.compare_digest(actual, expected)
        except (ValueError, AttributeError):
            return False

    def needs_setup(self):
        with closing(self.connect()) as db:
            return not db.execute("SELECT 1 FROM accounts LIMIT 1").fetchone()

    def create_account(self, login, password, first=False):
        login = login.strip().casefold()
        if not login or len(login) > 100 or any(c.isspace() or ord(c) < 32 for c in login):
            raise AuthError("auth_login_invalid")
        encoded = self.hash_password(password)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if first:
                if db.execute("SELECT 1 FROM accounts LIMIT 1").fetchone():
                    raise AuthError("auth_forbidden")
            else:
                self.require(True)
            try:
                uid = uuid.uuid4().hex
                db.execute("INSERT INTO accounts(user_id,login,password_hash,role,must_change) VALUES(?,?,?,?,?)",
                           (uid, login, encoded, 'admin' if first else 'employee', 0 if first else 1))
                return uid
            except sqlite3.IntegrityError:
                raise AuthError("auth_login_duplicate") from None

    def sign_in(self, login, password):
        self.sign_out()
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM accounts WHERE login=?", (login.strip().casefold(),)).fetchone()
        encoded = row['password_hash'] if row else 'pbkdf2_sha256$600000$' + '00' * 16 + '$' + '00' * 32
        valid = self.matches(password, encoded)
        if not row or not valid:
            raise AuthError("auth_invalid")
        self.session = {k: row[k] for k in ('user_id', 'login', 'role', 'must_change', 'version')}
        return dict(self.session)

    def sign_out(self):
        self.session = None
        self.epoch += 1

    def require(self, admin=False, password_change=False):
        if self.session is None:
            raise AuthError("auth_required")
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM accounts WHERE user_id=?", (self.session['user_id'],)).fetchone()
        if not row or row['version'] != self.session['version']:
            self.sign_out()
            raise AuthError("auth_required")
        if row['must_change'] and not password_change:
            raise AuthError("auth_change_required")
        if admin and row['role'] != 'admin':
            raise AuthError("auth_forbidden")
        return dict(self.session)

    def change_password(self, current, password):
        user = self.require(password_change=True)
        encoded = self.hash_password(password)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM accounts WHERE user_id=?", (user['user_id'],)).fetchone()
            if row['version'] != user['version'] or not self.matches(current, row['password_hash']):
                raise AuthError("auth_invalid")
            if self.matches(password, row['password_hash']):
                raise AuthError("auth_new_password")
            db.execute("UPDATE accounts SET password_hash=?,must_change=0,version=version+1 WHERE user_id=?",
                       (encoded, user['user_id']))
        self.session.update(must_change=0, version=user['version'] + 1)

    def employees(self):
        self.require(True)
        with closing(self.connect()) as db:
            return [dict(r) for r in db.execute("SELECT user_id,login FROM accounts WHERE role='employee' ORDER BY login")]

    def reset_password(self, user_id, password):
        self.require(True)
        encoded = self.hash_password(password)
        with closing(self.connect()) as db, db:
            result = db.execute("UPDATE accounts SET password_hash=?,must_change=1,version=version+1 WHERE user_id=? AND role='employee'",
                                (encoded, user_id))
            if result.rowcount != 1:
                raise AuthError("auth_forbidden")
