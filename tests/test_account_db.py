import hashlib
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, event, inspect, select, func
from sqlalchemy.exc import IntegrityError, OperationalError
from werkzeug.security import generate_password_hash, check_password_hash
from backend.account_db import account_engine_for, AccountDatabaseError, ACCOUNT_SCHEMA
from backend.auth import account_metadata, users, notebooks, sessions, empty_notebook
from backend.migrate_users import migrate_users, MigrationError


def make_source(path):
    engine=create_engine('sqlite:///'+str(path))
    account_metadata.create_all(engine)
    uid=str(uuid4());password_hash=generate_password_hash('preserved-test-password',method='scrypt')
    payload={**empty_notebook(),'notes':{'gitascan:13':'धर्म — preserved note'},'bookmarks':['gitascan:13'],'lastPage':'gitascan:13'}
    with engine.begin() as conn:
        conn.execute(users.insert().values(id=uid,email='migrated@example.test',name='Reader',password_hash=password_hash,created_at=123456))
        conn.execute(notebooks.insert().values(user_id=uid,payload=payload,revision=7,updated_at=123457))
        conn.execute(sessions.insert().values(token_hash='a'*64,user_id=uid,expires_at=2000000000))
    engine.dispose()
    return uid,password_hash,payload


def test_missing_cloud_setting_never_falls_back_to_local_users(monkeypatch):
    monkeypatch.delenv('SUPABASE_DB_URL',raising=False)
    monkeypatch.setenv('DATABASE_URL','sqlite:///old-books.db')
    with pytest.raises(AccountDatabaseError,match='Set SUPABASE_DB_URL'):account_engine_for()


@pytest.mark.parametrize('url',[
    'https://example.supabase.co/private-password',
    'not-a-uri-private-password',
    'sqlite:///users.db',
    'postgresql://postgres:private-password@example.test:bad/postgres',
    'postgresql://postgres@example.test/postgres',
    'postgresql://postgres:private-password@example.test/postgres?sslmode=disable',
])
def test_invalid_cloud_setting_fails_without_leaking_credentials(monkeypatch,url):
    monkeypatch.setenv('SUPABASE_DB_URL',url)
    with pytest.raises(AccountDatabaseError) as error:account_engine_for()
    assert 'private-password' not in str(error.value)


@pytest.mark.parametrize('scheme',['postgres','postgresql','postgresql+psycopg'])
def test_postgres_uri_normalization_and_private_schema(scheme):
    engine=account_engine_for(f'{scheme}://postgres.project:p%40ss@example.supabase.co:5432/postgres')
    try:
        assert engine.url.drivername=='postgresql+psycopg'
        assert engine.url.password=='p@ss'
        assert engine.url.query['sslmode']=='require'
        assert engine.get_execution_options()['schema_translate_map']=={None:ACCOUNT_SCHEMA}
        assert engine.hide_parameters
        assert engine.pool.size()==2
    finally:engine.dispose()


def test_certificate_verification_settings_are_retained():
    engine=account_engine_for('postgresql://reader:secret@example.test/postgres?sslmode=verify-full&sslrootcert=root.crt')
    assert engine.url.query=={'sslmode':'verify-full','sslrootcert':'root.crt'}
    engine.dispose()


def test_migration_preview_and_copy_preserve_data_and_source(tmp_path):
    source=tmp_path/'old.db';uid,password_hash,payload=make_source(source)
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    target=account_engine_for('sqlite:///'+str(tmp_path/'new.db'))
    preview=migrate_users(source,target)
    assert preview=={'users':1,'notebooks':1,'applied':False,'sessions_copied':0}
    assert inspect(target).get_table_names()==[]
    assert migrate_users(source,target,apply=True)['applied'] is True
    with target.connect() as conn:
        user=conn.execute(select(users)).mappings().one()
        note=conn.execute(select(notebooks)).mappings().one()
        assert user['id']==uid and user['password_hash']==password_hash
        assert check_password_hash(user['password_hash'],'preserved-test-password')
        assert note['payload']==payload and note['revision']==7
        assert conn.scalar(select(func.count()).select_from(sessions))==0
    with pytest.raises(MigrationError,match='already contains'):migrate_users(source,target,apply=True)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original
    target.dispose()


def test_migration_rollback_keeps_destination_empty(tmp_path):
    source=tmp_path/'old.db';make_source(source)
    target=account_engine_for('sqlite:///'+str(tmp_path/'new.db'))
    def fail_notebook(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith('INSERT INTO user_notebooks'):
            raise IntegrityError('injected failure',{},Exception('test rollback'))
    event.listen(target,'before_cursor_execute',fail_notebook)
    with pytest.raises(IntegrityError):migrate_users(source,target,apply=True)
    event.remove(target,'before_cursor_execute',fail_notebook)
    with target.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(users))==0
        assert conn.scalar(select(func.count()).select_from(notebooks))==0
    target.dispose()


def test_missing_source_is_not_created(tmp_path):
    source=tmp_path/'missing.db';target=account_engine_for('sqlite:///'+str(tmp_path/'new.db'))
    with pytest.raises(MigrationError,match='does not exist'):migrate_users(source,target)
    assert not source.exists()
    target.dispose()


def test_account_outage_returns_safe_error_and_preserves_cookie(client,app,monkeypatch):
    cookie=client.get_cookie('grantha_session').value
    def unavailable():raise OperationalError('SELECT secret','private-password',Exception('private-password'))
    monkeypatch.setattr(app.extensions['account_engine'],'connect',unavailable)
    response=client.get('/api/me/notebook')
    assert response.status_code==503 and response.json['code']=='database_unavailable'
    assert 'private-password' not in response.get_data(as_text=True)
    assert client.get_cookie('grantha_session').value==cookie
