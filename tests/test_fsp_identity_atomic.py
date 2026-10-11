"""Регрессии атомарной связи ФСП ID и миграции исторических треков."""
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, inspect, select
from sqlalchemy.exc import IntegrityError

from src.server import fsp_id
from src.server.models import Profile
from tests.test_api import client  # noqa: F401  (fixture)


MIGRATION = 'migrations.versions.f4b9d2e17a63_identity_uniqueness_track_integrity'


def _legacy_schema(connection):
    connection.exec_driver_sql(
        'CREATE TABLE profiles ('
        'user_id VARCHAR(64) PRIMARY KEY, specialization VARCHAR(30) NOT NULL, '
        'integrity_level VARCHAR(10), fsp_member_id VARCHAR(80))'
    )
    connection.exec_driver_sql(
        'CREATE TABLE confirmed_tracks ('
        'user_id VARCHAR(64) NOT NULL, specialization VARCHAR(30) NOT NULL, '
        'PRIMARY KEY (user_id, specialization))'
    )


def _run_upgrade(connection, monkeypatch):
    migration = import_module(MIGRATION)
    operations = Operations(MigrationContext.configure(connection))
    monkeypatch.setattr(migration, 'op', operations)
    migration.upgrade()


def test_migration_backfills_only_current_track_and_enforces_unique_link(monkeypatch):
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        _legacy_schema(connection)
        connection.execute(sa.text(
            "INSERT INTO profiles VALUES "
            "('candidate-a', 'backend', 'review', 'FSP-1001'), "
            "('candidate-b', 'backend', 'clean', NULL)"
        ))
        connection.execute(sa.text(
            "INSERT INTO confirmed_tracks VALUES "
            "('candidate-a', 'backend'), ('candidate-a', 'frontend'), "
            "('candidate-b', 'backend')"
        ))
        _run_upgrade(connection, monkeypatch)

        levels = connection.execute(sa.text(
            'SELECT user_id, specialization, integrity_level FROM confirmed_tracks '
            'ORDER BY user_id, specialization'
        )).all()
        assert levels == [
            ('candidate-a', 'backend', 'review'),
            ('candidate-a', 'frontend', None),
            ('candidate-b', 'backend', 'clean'),
        ]
        constraints = inspect(connection).get_unique_constraints('profiles')
        assert any(item['name'] == 'uq_profiles_fsp_member_id' and item['column_names'] == ['fsp_member_id']
                   for item in constraints)
        with pytest.raises(IntegrityError):
            connection.execute(sa.text(
                "INSERT INTO profiles VALUES ('candidate-c', 'qa', NULL, 'FSP-1001')"
            ))


def test_migration_refuses_duplicates_without_changing_or_identifying_rows(monkeypatch):
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        _legacy_schema(connection)
        connection.execute(sa.text(
            "INSERT INTO profiles VALUES "
            "('private-a', 'backend', NULL, 'FSP-secret'), "
            "('private-b', 'frontend', NULL, 'FSP-secret')"
        ))
        with pytest.raises(RuntimeError) as error:
            _run_upgrade(connection, monkeypatch)

        message = str(error.value)
        assert 'owner data resolution' in message
        assert 'private-a' not in message and 'private-b' not in message and 'FSP-secret' not in message
        assert 'integrity_level' not in {column['name'] for column in inspect(connection).get_columns('confirmed_tracks')}
        assert connection.execute(sa.text('SELECT COUNT(*) FROM profiles')).scalar_one() == 2


def test_unique_conflict_preserves_previous_link_and_outer_transaction(client, monkeypatch):
    factory = client.app.state.factory
    originals = {
        'demo-candidate-a': 'FSP-1001',
        'demo-candidate-b': 'FSP-1002',
    }
    with factory() as db:
        for candidate_id, member_id in originals.items():
            assert fsp_id.link(db, db.get(Profile, candidate_id), member_id) == 'linked'
        db.commit()

    with factory() as db:
        profile = db.get(Profile, 'demo-candidate-b')
        before = (profile.fsp_member_id, profile.fsp_state, profile.fsp_previous_state,
                  profile.fsp_evidence, profile.fsp_signal)
        # Имитируем устаревший результат предварительной проверки в гонке.
        monkeypatch.setattr(db, 'scalar', lambda statement: None)
        assert fsp_id.link(db, profile, 'FSP-1001') == 'taken'
        db.commit()

    with factory() as db:
        profile = db.get(Profile, 'demo-candidate-b')
        after = (profile.fsp_member_id, profile.fsp_state, profile.fsp_previous_state,
                 profile.fsp_evidence, profile.fsp_signal)
        assert after == before


def test_postgres_concurrent_links_have_one_winner_and_preserve_loser(client):
    engine, factory = client.app.state.engine, client.app.state.factory
    if engine.dialect.name != 'postgresql':
        pytest.skip('Проверка реальной конкурентной блокировки выполняется в PostgreSQL-прогоне')

    originals = {
        'demo-candidate-a': 'FSP-1004',
        'demo-candidate-b': 'FSP-1005',
    }
    with factory() as db:
        for candidate_id, member_id in originals.items():
            assert fsp_id.link(db, db.get(Profile, candidate_id), member_id) == 'linked'
        db.commit()

    barrier = Barrier(2)

    def synchronize_precheck(conn, cursor, statement, parameters, context, executemany):
        normalized = ' '.join(statement.lower().split())
        if normalized.startswith('select profiles.user_id') and 'where profiles.fsp_member_id =' in normalized:
            barrier.wait(timeout=10)

    def compete(candidate_id):
        with factory() as db:
            profile = db.get(Profile, candidate_id)
            status = fsp_id.link(db, profile, 'FSP-1001')
            db.commit()
            return candidate_id, status

    event.listen(engine, 'after_cursor_execute', synchronize_precheck)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = dict(pool.map(compete, originals))
    finally:
        event.remove(engine, 'after_cursor_execute', synchronize_precheck)

    assert sorted(results.values()) == ['linked', 'taken']
    loser = next(candidate_id for candidate_id, status in results.items() if status == 'taken')
    winner = next(candidate_id for candidate_id, status in results.items() if status == 'linked')
    with factory() as db:
        assert db.get(Profile, winner).fsp_member_id == 'FSP-1001'
        preserved = db.get(Profile, loser)
        assert preserved.fsp_member_id == originals[loser]
        assert preserved.fsp_state == 'verified'
        assert db.scalar(select(sa.func.count()).select_from(Profile).where(Profile.fsp_member_id == 'FSP-1001')) == 1
