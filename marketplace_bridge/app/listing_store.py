"""Durable master listings; deliberately separate from imported catalogue records."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone


class ListingStore:
    def __init__(self, path):
        self.path=path
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS listings(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS listing_results(listing_id TEXT NOT NULL, destination TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(listing_id,destination));
            CREATE TABLE IF NOT EXISTS listing_defaults(destination TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS listing_locks(listing_id TEXT PRIMARY KEY, owner TEXT NOT NULL);
            ''')
            # A prior process cannot finish an in-flight request after restart.
            for row in db.execute('SELECT listing_id,destination,payload FROM listing_results').fetchall():
                value=json.loads(row['payload'])
                if value.get('status')=='sending':
                    value.update(status='uncertain', message='Shop Sync restarted while sending. Check the shop before retrying.')
                    db.execute('UPDATE listing_results SET payload=? WHERE listing_id=? AND destination=?',
                               (json.dumps(value),row['listing_id'],row['destination']))
            db.execute('DELETE FROM listing_locks')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=30); db.row_factory=sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback(); raise
        finally: db.close()

    def save(self, value):
        value=json.loads(json.dumps(value)); identifier=str(value.get('id') or uuid.uuid4().hex)
        if len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):
            raise ValueError('Invalid listing ID')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT revision,payload FROM listings WHERE id=?',(identifier,)).fetchone()
            if old and value.get('revision') != old['revision']:
                raise ValueError('This listing changed in another tab. Reload it before saving.')
            if old:
                prior=json.loads(old['payload'])
                if {k:v for k,v in prior.items() if k not in ('id','revision')}=={k:v for k,v in value.items() if k not in ('id','revision')}:
                    return prior
            value.update(id=identifier,revision=(old['revision'] if old else 0)+1)
            db.execute('INSERT INTO listings VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload,updated=excluded.updated',
                       (identifier,value['revision'],json.dumps(value),datetime.now(timezone.utc).isoformat()))
        return value

    def get(self, identifier):
        with self.connect() as db: row=db.execute('SELECT payload FROM listings WHERE id=?',(identifier,)).fetchone()
        if not row: raise KeyError(identifier)
        return json.loads(row['payload'])

    def list(self):
        with self.connect() as db: rows=db.execute('SELECT payload,updated FROM listings ORDER BY updated DESC').fetchall()
        return [dict(json.loads(row['payload']),updated=row['updated']) for row in rows]

    def defaults(self, destination):
        with self.connect() as db: row=db.execute('SELECT payload FROM listing_defaults WHERE destination=?',(destination,)).fetchone()
        return json.loads(row['payload']) if row else {}

    def save_defaults(self, destination, value):
        with self.connect() as db: db.execute('INSERT INTO listing_defaults VALUES(?,?) ON CONFLICT(destination) DO UPDATE SET payload=excluded.payload',(destination,json.dumps(value)))

    def results(self, identifier):
        with self.connect() as db: rows=db.execute('SELECT destination,payload FROM listing_results WHERE listing_id=?',(identifier,)).fetchall()
        return {row['destination']:json.loads(row['payload']) for row in rows}

    def result(self, identifier, destination, **changes):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM listing_results WHERE listing_id=? AND destination=?',(identifier,destination)).fetchone()
            value=json.loads(row['payload']) if row else {}
            if 'mapping' in changes: changes['mapping']={**value.get('mapping',{}),**changes['mapping']}
            value.update(changes)
            db.execute('INSERT INTO listing_results VALUES(?,?,?) ON CONFLICT(listing_id,destination) DO UPDATE SET payload=excluded.payload',(identifier,destination,json.dumps(value)))
        return value

    def claim(self, identifier):
        owner=uuid.uuid4().hex
        try:
            with self.connect() as db: db.execute('INSERT INTO listing_locks VALUES(?,?)',(identifier,owner))
        except sqlite3.IntegrityError: raise ValueError('This listing is already being sent. Wait for its results.')
        return owner

    def release(self, identifier, owner):
        with self.connect() as db: db.execute('DELETE FROM listing_locks WHERE listing_id=? AND owner=?',(identifier,owner))
