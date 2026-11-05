"""Independent Etsy order scheduler and encrypted ledger; uses order-route ingress protection."""
import asyncio
import html
import json
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import httpx
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from .etsy import EtsyClient
from .etsy_broker import BrokerEtsyClient
from .etsy_orders import list_receipts, parse_receipt
from .order_models import OrderProblem
from .order_store import OrderStore
from .order_sync import OrderSync
from .order_shopify import OrderShopify
from .order_feedback import next_scan_seconds, summarize_run
from .workspace_navigation import workspace_navigation


def mount_etsy_orders(app,core,shopify_factory):
    store=OrderStore(core.settings.data_dir/'etsy-orders.db',core.secrets)
    lock=asyncio.Lock(); completed=None;tasks=set()
    old=store.settings().get('latest_run')
    if old and old.get('state')=='running':
        old.update(state='failed',message='Scan interrupted by restart; next scan will reconcile existing imports')
        store.configure(latest_run=old)

    def config_source():
        credential=core.get_credentials('etsy')
        if not str(credential.get('shop_id','')).isdigit(): raise OrderProblem('Connect your Etsy shop on the Dashboard first')
        return credential

    async def cycle(dry=False):
        nonlocal completed
        if lock.locked(): return
        async with lock:
            cfg=store.settings();states=[];new=0;writes=not dry
            run=dict(state='running',mode='preview' if dry else 'import',started_at=datetime.now(timezone.utc).isoformat())
            store.configure(latest_run=run,last_message='Checking Etsy connection…')
            source=None
            try:
                credential=config_source()
                if credential['shop_id']!=cfg['shop_id']: raise OrderProblem('Etsy shop changed; verify the saved shop before importing')
                target=core.get_credentials('shopify')
                if not cfg['target_shop'] or target.get('shop_domain')!=cfg['target_shop']: raise OrderProblem('Save and verify the connected Shopify destination first')
                source=BrokerEtsyClient(**credential) if credential.get('oauth_mode')=='publisher_broker' else EtsyClient(**credential)
                shopify=OrderShopify(shopify_factory(target),'Etsy')
                await shopify.check_scopes(writes=writes)
                receipts=await list_receipts(source)
                store.configure(active_packing_ids=[str(r['receipt_id']) for r in receipts])
                sync=OrderSync(store,shopify);verified=0
                for index,receipt in enumerate(receipts,1):
                    identity=str(receipt['receipt_id'])
                    store.configure(last_message=f'Checking Etsy order {index} of {len(receipts)}…')
                    # Re-fetch the receipt to catch a shipment/refund after queue retrieval.
                    detail=await source._get(f'/v3/application/shops/{source.shop_id}/receipts/{identity}')
                    if str(detail.get('receipt_id'))!=identity: raise OrderProblem('Etsy returned a different receipt; scan stopped')
                    try:
                        order=parse_receipt(detail,source.shop_id,cfg['weights'])
                    except OrderProblem as exc:
                        states.append('review')
                        reviews=store.settings().get('source_reviews',{})
                        reviews[identity]=str(exc);store.configure(source_reviews=reviews)
                        continue
                    reviews=store.settings().get('source_reviews',{});reviews.pop(identity,None);store.configure(source_reviews=reviews)
                    before=store.get(order.shop_id,identity)
                    await sync.import_order(order,writes=writes)
                    row=store.get(order.shop_id,identity);states.append(row['state'])
                    if row['state'] in {'preview','linked'}: verified+=1
                    if writes and row['state']=='linked' and row['message']=='Imported into Shopify' and not (before and before.get('shopify_id')):new+=1
                run.update(state='completed',completed_at=datetime.now(timezone.utc).isoformat(),counts=summarize_run(states,writes,new))
                store.configure(latest_run=run,last_message='Etsy scan completed',preview_verified=(not receipts or verified>0),last_success_at=run['completed_at'])
            except httpx.HTTPStatusError as exc:
                message=('Reconnect Etsy on the Dashboard to approve order-reading access. If shipping addresses are unavailable, this app needs Etsy approval.' if exc.response.status_code in {401,403} else f'Etsy service returned HTTP {exc.response.status_code}; scan will retry')
                run.update(state='failed',message=message,completed_at=datetime.now(timezone.utc).isoformat(),counts=summarize_run(states,writes,new))
                changes=dict(latest_run=run,last_message=message,preview_verified=False)
                if exc.response.status_code in {401,403}:changes['enabled']=False
                store.configure(**changes)
            except Exception as exc:
                message=str(exc) if isinstance(exc,OrderProblem) else 'Etsy scan failed; connection or response needs review'
                run.update(state='failed',message=message,completed_at=datetime.now(timezone.utc).isoformat(),counts=summarize_run(states,writes,new))
                store.configure(latest_run=run,last_message=message,preview_verified=False)
            finally:
                if source is not None:
                    try:core.save_credentials('etsy',source.credential_payload())
                    except Exception:
                        run.update(state='failed',message='Etsy connection could not be saved. Reconnect Etsy before importing again.',completed_at=datetime.now(timezone.utc).isoformat())
                        store.configure(latest_run=run,last_message=run['message'],enabled=False,preview_verified=False)
                completed=time.monotonic()

    def schedule(dry):
        task=asyncio.create_task(cycle(dry));tasks.add(task);task.add_done_callback(tasks.discard)

    previous=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async def poll():
            while True:
                if store.settings()['enabled'] and not lock.locked() and (completed is None or time.monotonic()-completed>=300): await cycle()
                await asyncio.sleep(5)
        async with previous(application):
            task=asyncio.create_task(poll())
            try: yield
            finally:
                task.cancel()
                for pending in tasks:pending.cancel()
                await asyncio.gather(task,*tasks,return_exceptions=True)
    app.router.lifespan_context=lifespan

    @app.get('/orders/etsy/status')
    async def status():
        cfg=store.settings();active=cfg.get('active_packing_ids',[])
        rows=[];reviewed=cfg.get('source_reviews',{})
        for row in store.list_orders(5000):
            if row['source_id'] not in active:continue
            rows.append(dict(id=row['source_id'],state='review' if row['source_id'] in reviewed else row['state'],message=reviewed.get(row['source_id'],row['message']),
                items=[{k:item.get(k) for k in ('title','variant','quantity','weight_key','weight_grams')} for item in row['payload'].get('items',[])],shopify_id=row['shopify_id']))
        displayed={row['id'] for row in rows}
        for identity,message in reviewed.items():
            if identity in active and identity not in displayed: rows.append(dict(id=identity,state='review',message=message,items=[]))
        return dict(running=lock.locked(),automatic=cfg['enabled'],latest_run=cfg.get('latest_run'),message=cfg['last_message'],
            next_scan_seconds=next_scan_seconds(cfg['enabled'],lock.locked(),completed,time.monotonic()),rows=rows,
            saved_at=cfg.get('settings_saved_at'),weights=cfg['weights'])

    @app.post('/orders/etsy/settings')
    async def settings(request:Request):
        value=await request.json();old=store.settings()
        if lock.locked():raise HTTPException(409,'Wait for the Etsy scan to finish before saving settings')
        if set(value)!={'enabled','weights','target_shop'} or type(value['enabled']) is not bool or not isinstance(value['weights'],dict):raise HTTPException(400,'Invalid Etsy settings')
        if any(not re.fullmatch(r'\d+:(?:\d+|None)',key) or type(weight) is not int or not 1<=weight<=100000 for key,weight in value['weights'].items()):raise HTTPException(400,'Each Etsy item weight must be 1–100000 grams')
        try:
            credential=config_source();target=core.get_credentials('shopify').get('shop_domain')
        except Exception:
            raise HTTPException(400,'Connect Etsy and Shopify on the Dashboard before saving order settings') from None
        if not target or value['target_shop']!=target:raise HTTPException(400,'Destination must match connected Shopify store')
        if old['shop_id'] and old['shop_id']!=credential['shop_id']:raise HTTPException(400,'Etsy source shop changed; use a separate installation')
        if old['target_shop'] and old['target_shop']!=target:raise HTTPException(400,'Shopify destination changed; use a separate installation')
        changed=old['weights']!=value['weights'] or old['target_shop']!=target
        if value['enabled'] and (changed or not old.get('preview_verified')):raise HTTPException(400,'Save with automatic import off, then complete an Etsy preview before enabling')
        stamp=datetime.now(timezone.utc).isoformat()
        store.configure(**value,shop_id=credential['shop_id'],settings_saved_at=stamp,preview_verified=old.get('preview_verified',False) and not changed)
        return {'saved_at':stamp}

    @app.post('/orders/etsy/scan')
    async def scan():
        if lock.locked():raise HTTPException(409,'Etsy scan is already running')
        schedule(True);return {'started':True}

    @app.post('/orders/etsy/import')
    async def import_now():
        if lock.locked():raise HTTPException(409,'Etsy scan is already running')
        if not store.settings().get('preview_verified'):raise HTTPException(400,'Complete an Etsy preview before importing')
        schedule(False);return {'started':True}

    @app.get('/orders/etsy',response_class=HTMLResponse)
    async def page(request:Request):
        base=request.headers.get('x-ingress-path','').rstrip('/')
        cfg=store.settings()
        try:target=core.get_credentials('shopify').get('shop_domain','')
        except Exception:target=''
        boot=json.dumps(dict(base=base,csrf=app.state.order_csrf,weights=cfg['weights'],enabled=cfg['enabled'],target_shop=cfg['target_shop'] or target)).replace('<','\\u003c')
        template=Path(__file__).with_name('etsy_order_page.html').read_text(encoding='utf-8')
        return HTMLResponse(template.replace('<!--NAV-->',workspace_navigation('etsy-orders',base)).replace('/*BOOT*/','const cfg='+boot+';'))
    return store
