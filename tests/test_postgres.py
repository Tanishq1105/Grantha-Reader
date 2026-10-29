"""Optional integration check against an EMPTY disposable local PostgreSQL DB."""
import os
import pytest
from sqlalchemy import select,text
from sqlalchemy.engine import make_url
from backend.account_db import account_engine_for,ACCOUNT_SCHEMA
from backend.auth import users,notebooks
from backend.app import create_app
from backend.migrate_users import migrate_users
from test_account_db import make_source


@pytest.mark.skipif(not os.getenv('GRANTHA_TEST_POSTGRES_URL'),reason='Disposable local PostgreSQL URL not supplied')
def test_postgres_migration_auth_isolation_and_schema_access(tmp_path,app):
    url=os.environ['GRANTHA_TEST_POSTGRES_URL']
    assert make_url(url).host in {'localhost','127.0.0.1','::1'},'Only a disposable local database may be used.'
    engine=account_engine_for(url)
    old=tmp_path/'source.db';uid,password_hash,payload=make_source(old)
    assert migrate_users(old,engine)['users']==1
    assert migrate_users(old,engine,apply=True)['applied']
    with engine.connect() as conn:
        assert conn.execute(select(users.c.password_hash)).scalar_one()==password_hash
        assert conn.execute(select(notebooks.c.payload)).scalar_one()==payload
        assert conn.scalar(text("SELECT to_regclass('public.users')")) is None
        flags=conn.execute(text("SELECT relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='grantha_private' AND c.relkind='r'")).scalars().all()
        assert len(flags)==4 and all(flags)
        for role in ('anon','authenticated','service_role'):
            if conn.scalar(text('SELECT 1 FROM pg_roles WHERE rolname=:role'),{'role':role}):
                assert not conn.scalar(text("SELECT has_schema_privilege(:role,'grantha_private','USAGE')"),{'role':role})
                assert not conn.scalar(text("SELECT has_table_privilege(:role,'grantha_private.users','SELECT')"),{'role':role})
    cloud=create_app(str(app.extensions['store'].engine.url),account_database_url=url)
    cloud.config['TESTING']=True
    def client():
        c=cloud.test_client();c.environ_base['HTTP_X_CSRF_TOKEN']=c.get('/api/auth/session').json['csrf_token'];return c
    a=client();response=a.post('/api/auth/login',json={'email':'migrated@example.test','password':'preserved-test-password'})
    assert response.status_code==200
    a.environ_base['HTTP_X_CSRF_TOKEN']=response.json['csrf_token']
    assert a.get('/api/me/notebook').json=={'notebook':payload,'revision':7}
    b=client();response=b.post('/api/auth/signup',json={'name':'Other','email':'other@example.test','password':'another-long-password'})
    assert response.status_code==201
    b.environ_base['HTTP_X_CSRF_TOKEN']=response.json['csrf_token']
    assert b.get('/api/me/notebook').json['notebook']['notes']=={}
    assert a.put('/api/me/notebook',json={'notebook':payload,'revision':7}).json['revision']==8
    assert a.put('/api/me/notebook',json={'notebook':payload,'revision':7}).status_code==409
    assert a.get('/api/health').json['account_database']=='postgresql'
    assert a.post('/api/me/password',json={'current_password':'preserved-test-password','new_password':'replacement-long-password'}).status_code==200
    c=client();assert c.post('/api/auth/login',json={'email':'migrated@example.test','password':'replacement-long-password'}).status_code==200
    engine.dispose();cloud.extensions['account_engine'].dispose()
