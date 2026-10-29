import hashlib,time
from sqlalchemy import select, inspect
from werkzeug.security import check_password_hash
from backend.auth import users,sessions,empty_notebook
from backend.db import initialize
from conftest import signup,PASSWORD

def anonymous(app):
 c=app.test_client();c.environ_base['HTTP_X_CSRF_TOKEN']=c.get('/api/auth/session').json['csrf_token'];return c

def test_password_hash_cookie_and_private_pdf(app):
 c,u=signup(app,' Mixed@Example.test ');assert u['email']=='mixed@example.test';assert set(u)=={'id','name','email'}
 with app.extensions['account_engine'].connect() as db:
  row=db.execute(select(users).where(users.c.id==u['id'])).mappings().one();assert row['password_hash'].startswith('scrypt:');assert PASSWORD not in row['password_hash'];assert check_password_hash(row['password_hash'],PASSWORD)
  with c.session_transaction() as s:token=hashlib.sha256(s['sid'].encode()).hexdigest()
  assert db.execute(select(sessions).where(sessions.c.token_hash==token)).first()
 cookie=c.get_cookie('grantha_session');assert cookie.http_only and cookie.same_site=='Lax'
 assert c.get('/api/books/gitascan/cover').headers['Cache-Control']=='private, no-store'

def test_anonymous_access_blocked(app):
 c=anonymous(app)
 for path in ['/api/books','/api/me/notebook','/api/passages/ramayana:59','/api/books/ramayana/pdf','/api/books/ramayana/cover']:assert c.get(path).status_code==401
 assert c.get('/api/health').status_code==200

def test_csrf_and_credentials_validation(app):
 c=anonymous(app);data={'name':'Reader','email':'csrf@example.test','password':PASSWORD}
 for token in ['', 'invalid', 'अ']:assert c.post('/api/auth/signup',json=data,headers={'X-CSRF-Token':token}).status_code==403
 assert c.post('/api/auth/signup',json=['bad']).status_code==400
 assert c.post('/api/auth/signup',data='invalid').status_code==415
 for patch in [{'name':''},{'email':'bad'},{'password':'short'},{'password':'x'*129}]:assert c.post('/api/auth/signup',json={**data,**patch}).status_code==400

def test_duplicate_login_and_revoked_cookie(app):
 c,u=signup(app);other=anonymous(app)
 assert other.post('/api/auth/signup',json={'name':'Other','email':u['email'].upper(),'password':PASSWORD}).status_code==409
 assert other.post('/api/auth/login',json={'email':u['email'],'password':'wrong'}).status_code==401
 r=other.post('/api/auth/login',json={'email':u['email'].upper(),'password':PASSWORD});assert r.json['user']==u
 cookie=c.get_cookie('grantha_session').value;assert c.post('/api/auth/logout',json={}).status_code==200
 replay=app.test_client();replay.set_cookie('grantha_session',cookie);assert replay.get('/api/books').status_code==401

def test_expiry(app):
 c,u=signup(app)
 with app.extensions['account_engine'].begin() as db:db.execute(sessions.update().where(sessions.c.user_id==u['id']).values(expires_at=int(time.time())-1))
 assert c.get('/api/books').status_code==401;assert c.get('/api/auth/session').json['user'] is None

def test_notebook_isolation_conflicts_and_new_session(app):
 a,u=signup(app);b,v=signup(app);note={**empty_notebook(),'notes':{'mahabharata1:101':'Private note'},'bookmarks':['ramayana:59'],'lastPage':'mahabharata1:101'}
 assert a.put('/api/me/notebook',json={'notebook':note,'revision':0}).json['revision']==1
 assert b.get('/api/me/notebook').json['notebook']['notes']=={}
 assert a.put('/api/me/notebook',json={'notebook':empty_notebook(),'revision':0}).status_code==409
 assert b.put('/api/me/notebook',json={'notebook':empty_notebook(),'revision':0,'user_id':u['id']}).status_code==200
 assert a.get('/api/me/notebook').json['notebook']==note
 new=anonymous(app);assert new.post('/api/auth/login',json={'email':u['email'],'password':PASSWORD}).status_code==200;assert new.get('/api/me/notebook').json['notebook']==note

def test_notebook_invalid_pages_and_revision(client):
 for note in [{**empty_notebook(),'bookmarks':['mahabharata1:999999']},{**empty_notebook(),'lastPage':'unknown:1'},{**empty_notebook(),'notes':{'gitascan:13':'x'*10001}}]:assert client.put('/api/me/notebook',json={'notebook':note,'revision':0}).status_code==400
 assert client.put('/api/me/notebook',json={'notebook':empty_notebook(),'revision':True}).status_code==400

def test_password_rotation_revokes_other_sessions(app):
 a,u=signup(app);b=anonymous(app);b.post('/api/auth/login',json={'email':u['email'],'password':PASSWORD});old=a.environ_base['HTTP_X_CSRF_TOKEN']
 assert a.post('/api/me/password',json=['bad']).status_code==400
 assert a.post('/api/me/password',json={'current_password':'wrong','new_password':'new-reader-passphrase'}).status_code==400
 r=a.post('/api/me/password',json={'current_password':PASSWORD,'new_password':'new-reader-passphrase'});assert r.status_code==200;assert r.json['csrf_token']!=old
 assert a.get('/api/books').status_code==200 and b.get('/api/books').status_code==401
 n=anonymous(app);assert n.post('/api/auth/login',json={'email':u['email'],'password':PASSWORD}).status_code==401;assert n.post('/api/auth/login',json={'email':u['email'],'password':'new-reader-passphrase'}).status_code==200

def test_login_rate_limit_and_disable_signup(app,monkeypatch):
 c=anonymous(app)
 for _ in range(12):assert c.post('/api/auth/login',json={'email':'rate@example.test','password':'wrong'}).status_code==401
 assert c.post('/api/auth/login',json={'email':'rate@example.test','password':'wrong'}).status_code==429
 monkeypatch.setenv('SIGNUP_ENABLED','false');assert c.get('/api/auth/session').json['signup_enabled'] is False
 assert c.post('/api/auth/signup',json={'name':'Reader','email':'blocked@example.test','password':PASSWORD}).status_code==403

def test_corpus_reload_preserves_account_data(app):
 c,u=signup(app);note={**empty_notebook(),'notes':{'gitascan:13':'Keep through update'}};c.put('/api/me/notebook',json={'notebook':note,'revision':0})
 initialize(app.extensions['store'].engine,replace=True)
 assert c.get('/api/auth/session').json['user']==u;assert c.get('/api/me/notebook').json['notebook']==note
 assert 'users' not in inspect(app.extensions['store'].engine).get_table_names()
