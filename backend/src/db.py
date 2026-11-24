from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def connect():
    return psycopg.connect('', row_factory=dict_row, connect_timeout=4)


def migrate():
    with connect() as db:
        db.execute('SELECT pg_advisory_xact_lock(106500)')
        for path in sorted(Path('/app/migrations').glob('*.sql')):
            db.execute(path.read_text())
