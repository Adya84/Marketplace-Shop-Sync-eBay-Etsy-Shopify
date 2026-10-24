import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


class OrderStore:
    def __init__(self,path,box):
        self.path=path; self.box=box
        with self.connect() as conn:
            conn.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS order_bridge (
              shop TEXT, source_id TEXT, payload TEXT NOT NULL, state TEXT NOT NULL,
              message TEXT NOT NULL DEFAULT '', shopify_id TEXT, tracking TEXT NOT NULL DEFAULT '[]',
              updated_at TEXT NOT NULL, PRIMARY KEY(shop,source_id));
            CREATE TABLE IF NOT EXISTS order_bridge_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        conn=sqlite3.connect(self.path,timeout=30); conn.row_factory=sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally: conn.close()

    def settings(self):
        result={'enabled':False,'tracking_enabled':False,'shop_id':'','shop_name':'',
                'weights':{},'carriers':{},'target_shop':'','last_message':'Not started'}
        with self.connect() as conn:
            result.update({row['key']:json.loads(row['value']) for row in conn.execute('SELECT * FROM order_bridge_settings')})
        return result

    def configure(self,**values):
        with self.connect() as conn:
            for key,value in values.items():
                conn.execute('INSERT OR REPLACE INTO order_bridge_settings VALUES (?,?)',(key,json.dumps(value)))

    def claim(self,order):
        order.validate_identity()
        payload=self.box.encrypt(json.dumps(order.payload()))
        stamp=datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            cur=conn.execute('''INSERT INTO order_bridge(shop,source_id,payload,state,updated_at)
                VALUES (?,?,?,'claimed',?) ON CONFLICT(shop,source_id) DO UPDATE SET
                state='claimed',payload=excluded.payload,updated_at=excluded.updated_at
                WHERE order_bridge.state IN ('preview','review') AND order_bridge.shopify_id IS NULL''',
                (order.shop_id,order.order_id,payload,stamp))
            return cur.rowcount == 1

    def record(self,order,state,message='',shopify_id=None,tracking=None):
        order.validate_identity()
        with self.connect() as conn:
            conn.execute('''INSERT INTO order_bridge VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(shop,source_id) DO UPDATE SET payload=excluded.payload,state=excluded.state,
            message=excluded.message,shopify_id=COALESCE(excluded.shopify_id,order_bridge.shopify_id),
            tracking=CASE WHEN ? THEN excluded.tracking ELSE order_bridge.tracking END,updated_at=excluded.updated_at''',
            (order.shop_id,order.order_id,self.box.encrypt(json.dumps(order.payload())),state,message,
             shopify_id,json.dumps(tracking or []),datetime.now(timezone.utc).isoformat(),tracking is not None))

    def _decode(self,row):
        if not row: return None
        result=dict(row); result['payload']=json.loads(self.box.decrypt(result['payload']))
        result['tracking']=json.loads(result['tracking'])
        return result

    def get(self,shop,source_id):
        with self.connect() as conn:
            return self._decode(conn.execute('SELECT * FROM order_bridge WHERE shop=? AND source_id=?',(shop,source_id)).fetchone())

    def source_failure(self,order):
        previous=self.get(order.shop_id,order.order_id)
        if previous and previous['state']=='validation_review':
            self.record(order,'validation_review',previous['message'],previous['shopify_id']); return
        state=previous['state'] if previous and previous['state'] in {'claimed','uncertain','tracking_uncertain'} else 'review'
        self.record(order,state,'TikTok detail could not be verified; inspect in browser')

    def list_orders(self,limit=200):
        with self.connect() as conn:
            return [self._decode(row) for row in conn.execute('SELECT * FROM order_bridge ORDER BY updated_at DESC LIMIT ?',(limit,))]
