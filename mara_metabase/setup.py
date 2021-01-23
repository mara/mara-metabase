"""
Functions for setting up Metabase by directly writing to its metadata database

Especially useful for the initial setup of a Metabase instance (when the API is not available yet).
"""

import json
import uuid
from functools import singledispatch

import bcrypt
import mara_db.dbs
import mara_db.postgresql

from . import config


def setup():
    """
    Sets the admin user credentials, adds a db connection and sets a few other configurations.

    Patch or copy this method if you want to something differently.
    """
    print('\033[36m.. creating admin user \033[0m')
    add_user(email=config.metabase_admin_email(),
             first_name=config.metabase_admin_first_name(),
             last_name=config.metabase_admin_last_name(),
             password=config.metabase_admin_password(),
             is_superuser=True,
             groups=['Administrators', 'All users'])

    print('\033[36m.. updating databases\033[0m')
    update_databases({config.metabase_data_db_name(): mara_db.dbs.db(config.metabase_data_db_alias())})

    print('\033[36m.. updating settings\033[0m')
    update_settings([("anon-tracking-enabled", False),
                     ("admin-email", config.metabase_admin_email()),
                     ("enable-nested-queries", False),
                     ("enable-public-sharing", False),
                     ("enable-query-caching", False),
                     ("enable-xrays", False),
                     ("report-timezone", 'Europe/Berlin'),
                     ("humanization-strategy", 'none'),
                     ("show-homepage-data", False)])


def add_user(first_name: str, last_name: str, email: str, password: str,
             is_superuser: bool, groups: [str]):
    """Creates a user in Metabase by writing directly to the metadata db"""

    # rebuilt password hashing logic from
    # https://github.com/metabase/metabase/blob/master/src/metabase/models/user.clj
    password_salt = str(uuid.uuid4())
    encrypted_password = bcrypt.hashpw((password_salt + password).encode('utf-8'),
                                       bcrypt.gensalt(rounds=10, prefix=b"2a")).decode("utf-8")

    with mara_db.postgresql.postgres_cursor_context(config.metabase_metadata_db_alias()) as cursor:
        cursor.execute(f"""
INSERT INTO core_user (email, first_name, last_name, password, password_salt, 
                       date_joined, is_superuser, is_active)
VALUES ({'%s'}, {'%s'}, {'%s'}, 
        {'%s'}, {'%s'}, 
        current_timestamp, {'%s'}, TRUE)
ON CONFLICT (email) DO UPDATE 
   SET first_name=EXCLUDED.first_name,
       last_name=EXCLUDED.last_name,
       password=EXCLUDED.password,
       password_salt=EXCLUDED.password_salt,
       is_superuser=EXCLUDED.is_superuser,
       is_active=EXCLUDED.is_active
""", (email, first_name, last_name, encrypted_password, password_salt, is_superuser))
        print(cursor.query.decode('utf-8'))

        cursor.execute(f'''
INSERT INTO permissions_group_membership (user_id, group_id)
SELECT core_user.id, permissions_group.id
FROM core_user, permissions_group
WHERE email = {'%s'} AND permissions_group.name::TEXT IN {'%s'}
ON CONFLICT DO NOTHING;
    ''',
                       (email, tuple(groups)))
        print(cursor.query.decode('utf-8'))


@singledispatch
def db_engine(db: mara_db.dbs.DB) -> str:
    """Returns the metabase db engine for a mara DB config"""
    raise NotImplementedError(f'Please implement db_engine for type "{db.__class__.__name__}"')


@singledispatch
def db_details(db: mara_db.dbs.DB) -> dict:
    """Returns a Metabase database configuration from a mara DB config"""
    raise NotImplementedError(f'Please implement db_engine for type "{db.__class__.__name__}"')


@db_engine.register(mara_db.dbs.PostgreSQLDB)
def __(_):
    return 'postgres'


@db_details.register(mara_db.dbs.PostgreSQLDB)
def __(db: mara_db.dbs.PostgreSQLDB):
    return {"host": db.host, "port": db.port, "dbname": db.database, "user": db.user, "ssl": db.sslmode,
            "password": db.password}

@db_engine.register(mara_db.dbs.SQLServerDB)
def __(_):
    return 'sqlserver'

@db_details.register(mara_db.dbs.SQLServerDB)
def __(db: mara_db.dbs.SQLServerDB):
    # NOTE: The SQL server port is fix here because mara_db.dbs.SQLServerDB does not have the port
    # NOTE: We use here the SQL Server default instance 'MSSQLSERVER'. Named instances are not supported via mara_db.dbs.SQLServerDB yet
    return {"host": db.host, "instance": "MSSQLSERVER", "port": db.port, "db": db.database, "user": db.user, "ssl": False,
            "password": db.password, "additional-options": "encrypt=true", "tunnel-endabled": False}

def update_databases(databases: {str: mara_db.dbs.DB}):
    """
    Creates or updates a list of databases in the Metabase metadata db (and removes all others)

    Args:
        databases: A mapping of database names to database configurations
    """
    with mara_db.postgresql.postgres_cursor_context(config.metabase_metadata_db_alias()) as cursor:
        cursor.execute('SELECT id, name FROM metabase_database')
        existing_database_ids = {name: id for id, name in cursor.fetchall()}

        if len(existing_database_ids) != len(databases):
            cursor.execute(f"TRUNCATE metabase_database CASCADE;")
            print(cursor.query.decode('utf-8'))

            for name, db in databases.items():
                cursor.execute(f"""
INSERT INTO metabase_database (created_at, updated_at, name, details, engine, is_sample) 
VALUES (current_timestamp, current_timestamp, {'%s'}, {'%s'}, {'%s'}, false);
""",
                               (name, json.dumps(db_details(db)), db_engine(db)))
                print(cursor.query.decode('utf-8'))

        else:
            for name, id in zip(databases.keys(), existing_database_ids.values()):
                db = databases[name]
                cursor.execute(f"""
UPDATE metabase_database
SET details = {'%s'}, engine = {'%s'}, name={'%s'}, is_sample=false
WHERE id = {'%s'};
""",
                               (json.dumps(db_details(db)), db_engine(db), name, id))
                print(cursor.query.decode('utf-8'))


def update_settings(settings: [(str, str)]):
    """
    Sets a list of settings (key, value)

    See https://git.xyser.com/Test/metabase/blob/master/src/metabase/public_settings.clj
    """
    from psycopg2.extras import execute_values

    with mara_db.postgresql.postgres_cursor_context(config.metabase_metadata_db_alias()) as cursor:
        execute_values(cursor, f"""
INSERT INTO setting (key, value)
VALUES {'%s'}
ON CONFLICT (key) DO UPDATE
    SET value = EXCLUDED.value
""", settings)
        print(cursor.query.decode('utf-8'))

        cursor.execute(f"""
DELETE FROM setting WHERE key = 'setup-token';
""")
        print(cursor.query.decode('utf-8'))
