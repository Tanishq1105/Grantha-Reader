"""User accounts, revocable sessions and private notebooks in Supabase PostgreSQL."""
from datetime import timedelta
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from uuid import uuid4
from flask import g, jsonify, request, session
from sqlalchemy import MetaData, Table, Column, String, Integer, JSON, ForeignKey, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from werkzeug.security import generate_password_hash, check_password_hash
from .db import ROOT
from .account_db import initialize_account_tables

account_metadata = MetaData()
users = Table('users', account_metadata,
    Column('id', String(36), primary_key=True),
    Column('email', String(254), nullable=False, unique=True),
    Column('name', String(80), nullable=False),
    Column('password_hash', String(256), nullable=False),
    Column('created_at', Integer, nullable=False))
sessions = Table('user_sessions', account_metadata,
    Column('token_hash', String(64), primary_key=True),
    Column('user_id', String(36), ForeignKey('users.id'), nullable=False, index=True),
    Column('expires_at', Integer, nullable=False))
notebooks = Table('user_notebooks', account_metadata,
    Column('user_id', String(36), ForeignKey('users.id'), primary_key=True),
    Column('payload', JSON, nullable=False),
    Column('revision', Integer, nullable=False),
    Column('updated_at', Integer, nullable=False))
attempts = Table('auth_attempts', account_metadata,
    Column('key', String(100), primary_key=True),
    Column('count', Integer, nullable=False),
    Column('expires_at', Integer, nullable=False))


def local_secret():
    directory = ROOT / 'instance'
    directory.mkdir(exist_ok=True)
    path = directory / 'session-secret'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    with os.fdopen(fd, 'w') as stream:
        value = secrets.token_hex(32)
        stream.write(value)
    return value


def empty_notebook():
    return {'version': 1, 'notes': {}, 'bookmarks': [], 'read': [], 'lastPage': None}


def public_user(user):
    return {key: user[key] for key in ('id', 'email', 'name')}


def initialize_auth(app, engine, store):
    secret = os.getenv('SECRET_KEY', '').strip()
    secure = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
    if os.getenv('APP_ENV') == 'production' and (not secret or not secure):
        raise ValueError('Production requires SECRET_KEY and SESSION_COOKIE_SECURE=true behind HTTPS.')
    if secret and len(secret) < 32:
        raise ValueError('SECRET_KEY must contain at least 32 characters.')
    app.config.update(SECRET_KEY=secret or local_secret(), SESSION_COOKIE_NAME='grantha_session',
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=secure,
                      SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=timedelta(days=7),
                      SESSION_REFRESH_EACH_REQUEST=False)
    initialize_account_tables(engine, account_metadata)
    app.extensions['account_engine'] = engine
    dummy_hash = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')

    def token_hash():
        return hashlib.sha256(str(session.get('sid', '')).encode()).hexdigest()

    def csrf_token():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return session['csrf']

    def response_for(user, code=200):
        return jsonify(user=public_user(user) if user else None, csrf_token=csrf_token(), signup_enabled=os.getenv('SIGNUP_ENABLED','true').lower()=='true'), code

    def issue_session(conn, uid):
        conn.execute(sessions.delete().where(sessions.c.token_hash == token_hash()))
        now = int(time.time())
        conn.execute(sessions.delete().where(sessions.c.expires_at <= now))
        session.clear()
        session.permanent = True
        session['sid'] = secrets.token_urlsafe(48)
        session['csrf'] = secrets.token_urlsafe(32)
        conn.execute(sessions.insert().values(token_hash=token_hash(), user_id=uid, expires_at=now + 7 * 86400))

    def budget(action, identity, limit, seconds=600):
        now = int(time.time())
        key = f'{action}:{now // seconds}:' + hashlib.sha256(identity.encode()).hexdigest()
        with engine.begin() as conn:
            insert = pg_insert if engine.dialect.name == 'postgresql' else sqlite_insert
            statement = insert(attempts).values(key=key, count=1, expires_at=now + seconds)
            statement = statement.on_conflict_do_update(index_elements=[attempts.c.key],
                set_={'count': attempts.c.count + 1}, where=attempts.c.count < limit)
            row = conn.execute(statement.returning(attempts.c.count)).first()
            conn.execute(attempts.delete().where(attempts.c.expires_at < now))
        return row is not None

    def credentials():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('Send a JSON object.')
        email, password = data.get('email'), data.get('password')
        if not isinstance(email, str) or not isinstance(password, str):
            raise ValueError('Enter your email and password.')
        email = email.strip().casefold()
        if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise ValueError('Enter a valid email address.')
        if not 1 <= len(password) <= 128:
            raise ValueError('Password must contain at most 128 characters.')
        return data, email, password

    @app.before_request
    def protect_api():
        g.user = None
        if not request.path.startswith('/api/'):
            return
        if request.path == '/api/me/notebook':
            request.max_content_length = 2_000_000
        if request.path == '/api/health':
            return
        if session.get('sid'):
            with engine.connect() as conn:
                user = conn.execute(select(users).join(sessions, sessions.c.user_id == users.c.id)
                    .where(sessions.c.token_hash == token_hash(), sessions.c.expires_at > int(time.time()))).mappings().first()
            if user:
                g.user = dict(user)
            else:
                session.clear()
        public = {'/api/auth/session', '/api/auth/signup', '/api/auth/login'}
        if request.path not in public and not g.user:
            return jsonify(error='Please sign in to continue.', code='authentication_required'), 401
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            supplied = request.headers.get('X-CSRF-Token', '')
            expected = session.get('csrf', '')
            if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
                return jsonify(error='Your session changed. Refresh the page and try again.', code='csrf_failed'), 403
            if not request.is_json:
                return jsonify(error='Send application/json.'), 415

    @app.after_request
    def private_responses(response):
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'private, no-store'
            response.vary.add('Cookie')
        return response

    @app.get('/api/auth/session')
    def current_session():
        return response_for(g.user)

    @app.post('/api/auth/signup')
    def signup():
        if os.getenv('SIGNUP_ENABLED','true').lower()!='true':
            return jsonify(error='New accounts are disabled for this reading room. Contact its owner.'), 403
        data, email, password = credentials()
        name = data.get('name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError('Name must contain 1 to 80 characters.')
        if len(password) < 12:
            raise ValueError('Use a password with at least 12 characters.')
        if not budget('signup', request.remote_addr or 'local', 10, 3600):
            return jsonify(error='Too many sign-up attempts. Try again later.'), 429
        user = {'id': str(uuid4()), 'email': email, 'name': name.strip(),
                'password_hash': generate_password_hash(password, method='scrypt'), 'created_at': int(time.time())}
        try:
            with engine.begin() as conn:
                conn.execute(users.insert().values(**user))
                conn.execute(notebooks.insert().values(user_id=user['id'], payload=empty_notebook(), revision=0, updated_at=int(time.time())))
                issue_session(conn, user['id'])
        except IntegrityError:
            return jsonify(error='An account with this email already exists. Sign in instead.'), 409
        return response_for(user, 201)

    @app.post('/api/auth/login')
    def login():
        _, email, password = credentials()
        if not budget('login-ip', request.remote_addr or 'local', 40) or not budget('login-email', email, 12):
            return jsonify(error='Too many sign-in attempts. Try again in 10 minutes.'), 429
        with engine.connect() as conn:
            user = conn.execute(select(users).where(users.c.email == email)).mappings().first()
        valid = check_password_hash(user['password_hash'] if user else dummy_hash, password)
        if not user or not valid:
            return jsonify(error='Email or password is incorrect.'), 401
        with engine.begin() as conn:
            issue_session(conn, user['id'])
        return response_for(user)

    @app.post('/api/auth/logout')
    def logout():
        with engine.begin() as conn:
            conn.execute(sessions.delete().where(sessions.c.token_hash == token_hash()))
        session.clear()
        return response_for(None)

    @app.post('/api/me/password')
    def change_password():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('Send a JSON object.')
        old, new = data.get('current_password'), data.get('new_password')
        if not isinstance(old, str) or len(old) > 128 or not isinstance(new, str) or not 12 <= len(new) <= 128:
            raise ValueError('Enter your current password and a new password of 12 to 128 characters.')
        if not budget('password', g.user['id'], 10):
            return jsonify(error='Too many attempts. Try again in 10 minutes.'), 429
        if not check_password_hash(g.user['password_hash'], old):
            return jsonify(error='Current password is incorrect.'), 400
        with engine.begin() as conn:
            conn.execute(users.update().where(users.c.id == g.user['id']).values(password_hash=generate_password_hash(new, method='scrypt')))
            conn.execute(sessions.delete().where(sessions.c.user_id == g.user['id']))
            issue_session(conn, g.user['id'])
        return response_for(g.user)

    def validate_notebook(value):
        if not isinstance(value, dict) or value.get('version') != 1:
            raise ValueError('Invalid notebook format.')
        result = empty_notebook()
        def valid_id(pid):
            return isinstance(pid, str) and pid in store.by_id
        for key in ('bookmarks', 'read'):
            entries = value.get(key)
            if not isinstance(entries, list) or len(entries) > 50000 or any(not valid_id(pid) for pid in entries):
                raise ValueError('Invalid notebook page references.')
            result[key] = list(dict.fromkeys(entries))
        notes = value.get('notes')
        if not isinstance(notes, dict) or len(notes) > 5000:
            raise ValueError('Invalid notes.')
        for pid, note in notes.items():
            if not valid_id(pid) or not isinstance(note, str) or len(note) > 10000:
                raise ValueError('Invalid note or page reference.')
        result['notes'] = dict(notes)
        last = value.get('lastPage')
        if last is not None and not valid_id(last):
            raise ValueError('Invalid reading position.')
        result['lastPage'] = last
        if len(json.dumps(result).encode()) > 1_900_000:
            raise ValueError('Notebook is too large. Export and reduce its size.')
        return result

    @app.get('/api/me/notebook')
    def get_notebook():
        with engine.connect() as conn:
            row = conn.execute(select(notebooks).where(notebooks.c.user_id == g.user['id'])).mappings().one()
        return jsonify(notebook=row['payload'], revision=row['revision'])

    @app.put('/api/me/notebook')
    def save_notebook():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or type(data.get('revision')) is not int or data['revision'] < 0:
            raise ValueError('Send the notebook revision with your changes.')
        value = validate_notebook(data.get('notebook'))
        with engine.begin() as conn:
            result = conn.execute(notebooks.update().where(notebooks.c.user_id == g.user['id'], notebooks.c.revision == data['revision'])
                .values(payload=value, revision=data['revision'] + 1, updated_at=int(time.time())))
            if result.rowcount != 1:
                return jsonify(error='This notebook changed on another device. Export your unsaved copy before reloading.', code='notebook_conflict'), 409
        return jsonify(revision=data['revision'] + 1)
