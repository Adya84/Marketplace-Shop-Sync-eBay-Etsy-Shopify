"""Order-only beta workspace. All routes require HA Ingress's socket peer."""
import asyncio
import contextlib
import html
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import quote
import httpx
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from .order_browser import TikTokBrowser
from .order_models import SourceOrder, OrderProblem, SignInRequired
from .order_store import OrderStore
from .order_shopify import OrderShopify
from .order_sync import OrderSync
from .workspace_navigation import workspace_navigation
from .order_feedback import next_scan_seconds, summarize_run
from pathlib import Path


async def desktop_ready(port=5900):
    writer=None
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection('127.0.0.1',port),2)
        banner=await asyncio.wait_for(reader.readexactly(12),2)
        return banner.startswith(b'RFB ') and banner.endswith(b'\n')
    except (OSError,asyncio.TimeoutError,asyncio.IncompleteReadError):
        return False
    finally:
        if writer:
            writer.close()
            with contextlib.suppress(OSError): await writer.wait_closed()


def ingress_peer(host):
    return host=='172.30.32.2' or (os.getenv('BRIDGE_DEVELOPMENT')=='1' and host in {'127.0.0.1','::1','testclient'})


async def poll_orders(enabled,cycle,refresh,completed_at,sleep=asyncio.sleep,clock=time.monotonic):
    refreshed_for=None
    while True:
        if not enabled():
            await sleep(10); continue
        finished=completed_at()
        if finished is None or clock()-finished>=300:
            await cycle()
            await sleep(1); continue
        if clock()-finished>=240 and refreshed_for!=finished:
            if await refresh() is not False: refreshed_for=finished
            await sleep(1); continue
        deadline=finished+(300 if refreshed_for==finished else 240)
        await sleep(min(10,max(1,deadline-clock())))

def mount_orders(app,core,client_factory):
    store=OrderStore(core.settings.data_dir/'orders.db',core.secrets)
    interrupted=store.settings().get('latest_run')
    if interrupted and interrupted.get('state')=='running':
        interrupted.update(state='failed',completed_at=datetime.now(timezone.utc).isoformat(),message='Scan interrupted by a restart; imported orders will be reconciled on the next scan')
        store.configure(latest_run=interrupted)
    browser=TikTokBrowser(core.settings.data_dir/'tiktok-browser',store.settings,
                         lambda message:store.configure(last_message=message))
    csrf=secrets.token_urlsafe(32)
    instance=secrets.token_hex(16) # Public restart marker, never an authentication token.
    run_lock=asyncio.Lock()
    app.state.tiktok_browser=browser
    app.state.tiktok_browser_lock=run_lock
    def browser_view_url(base):
        socket=base+'/orders/desktop/websockify?token='+csrf
        return base+'/orders/desktop/vnc.html?autoconnect=true&reconnect=true&reconnect_delay=3000&resize=scale&path='+quote(socket,safe='')
    app.state.tiktok_browser_view_url=browser_view_url
    last_completed=None
    tasks=set()
    previous=app.router.lifespan_context

    async def cycle(dry=False,manual=False):
        nonlocal last_completed
        if run_lock.locked(): return
        async with run_lock:
            stage='Shopify connection'
            run={'started_at':datetime.now(timezone.utc).isoformat(),'state':'running','mode':'preview' if dry else 'import'}
            states=[]; imported=0; writes=False
            store.configure(latest_run=run,results_hidden=False)
            try:
                store.configure(last_message='Checking Shopify connection…')
                config=store.settings()
                credential=core.get_credentials('shopify')
                domain=credential.get('shop_domain','')
                if domain!=config['target_shop'] or not domain:
                    raise OrderProblem('Shopify destination changed or is not verified; check settings')
                writes=(manual or config['enabled']) and not dry
                shopify=OrderShopify(client_factory(credential))
                await shopify.check_scopes(writes=writes)
                stage='TikTok browser'
                store.configure(last_message='Checking TikTok browser…')
                await asyncio.to_thread(browser.start)
                stage='TikTok shipping queue'
                store.configure(last_message='Reading TikTok shipping queue…')
                ids=await asyncio.to_thread(browser.scan_ids)
                store.configure(active_packing_ids=ids)
                sync=OrderSync(store,shopify)
                ready=0; failures=0
                pending=list(dict.fromkeys(ids))
                for position,order_id in enumerate(pending,1):
                    stage='order verification'
                    store.configure(last_message=f'Checking order {position} of {len(pending)}…')
                    try:
                        order=await asyncio.to_thread(browser.detail,order_id)
                    except SignInRequired:
                        raise
                    except Exception as exc:
                        # Retain a durable review record without logging customer content.
                        old=store.get(config['shop_id'],order_id)
                        payload=old['payload'] if old else dict(shop_id=config['shop_id'],order_id=order_id,
                            status='Unknown',currency='GBP',total='0.00',shipping='0.00',address={},items=[],seller_fulfilled=False)
                        failures+=1
                        states.append('source_failed')
                        reason=str(exc) if isinstance(exc,OrderProblem) else type(exc).__name__
                        store.source_failure(SourceOrder(**payload),reason)
                        continue
                    # Never backfill already-dispatched historical orders.
                    if order.status!='Awaiting packing': continue
                    before=store.get(order.shop_id,order_id)
                    await sync.import_order(order,writes=writes)
                    after=store.get(order.shop_id,order_id)
                    states.append(after['state'] if after else 'source_failed')
                    if writes and after and after['state']=='linked' and not (before and before.get('shopify_id')) and after['message']=='Imported into Shopify': imported+=1
                    try:
                        order.validate()
                        if store.get(order.shop_id,order_id)['state'] in {'preview','linked'}: ready+=1
                    except OrderProblem: pass
                    # Tracking submission remains manual in this beta; show verified data only.
                    await sync.sync_tracking(order,browser,writes=False)
                # Detail failures remain durable review rows and never reach
                # creation. They must not block independently validated orders.
                if dry: store.configure(preview_verified=not ids or ready>0)
                run.update(state='completed',completed_at=datetime.now(timezone.utc).isoformat(),counts=summarize_run(states,writes,imported))
                store.configure(latest_run=run)
                store.configure(last_success_at=datetime.now(timezone.utc).isoformat())
                store.configure(last_message=f'Scan complete: {len(ids)} Awaiting packing orders inspected. '+
                                ('Preview only.' if not writes else 'Import run finished.')+
                                (f' {failures} orders need source review.' if failures else ''))
            except SignInRequired as exc:
                store.configure(enabled=False,preview_verified=False,last_message=str(exc))
            except OrderProblem as exc:
                store.configure(last_message=str(exc))
            except Exception as exc:
                # Never expose raw driver/HTTP errors: they may contain buyer
                # information, request headers or session capabilities.
                from .order_browser import browser_failure
                store.configure(last_message=f'Scan stopped during {stage}: {browser_failure(exc)}.')
            finally:
                if run['state']=='running':
                    run.update(state='failed',completed_at=datetime.now(timezone.utc).isoformat(),message=store.settings()['last_message'],counts=summarize_run(states,writes,imported))
                    store.configure(latest_run=run)
                last_completed=time.monotonic()

    def schedule(coro):
        task=asyncio.create_task(coro); tasks.add(task); task.add_done_callback(tasks.discard)

    async def refresh_between_checks():
        if run_lock.locked(): return False
        async with run_lock:
            try:
                store.configure(last_message='Refreshing TikTok browser between checks…')
                refreshed=await asyncio.to_thread(browser.refresh_idle)
                store.configure(last_message='TikTok browser refreshed; next automatic check in about one minute.'
                                if refreshed else 'TikTok browser is not started; next check will start it.')
            except SignInRequired as exc: store.configure(enabled=False,preview_verified=False,last_message=str(exc))
            except OrderProblem as exc: store.configure(last_message=str(exc))
            except Exception as exc:
                from .order_browser import browser_failure
                store.configure(last_message=f'Between-check browser refresh failed: {browser_failure(exc)}; next check will retry.')

    @asynccontextmanager
    async def lifespan(application):
        async with previous(application):
            poll_task=asyncio.create_task(poll_orders(lambda:store.settings()['enabled'],cycle,refresh_between_checks,
                                                    lambda:last_completed))
            try: yield
            finally:
                poll_task.cancel()
                for task in tasks: task.cancel()
                await asyncio.gather(poll_task,*tasks,return_exceptions=True)
                await asyncio.to_thread(browser.close)
    app.router.lifespan_context=lifespan

    @app.middleware('http')
    async def protect(request:Request,call_next):
        if request.url.path.startswith('/orders'):
            if not request.client or not ingress_peer(request.client.host):
                return Response('Open this page through Home Assistant Ingress.',status_code=403)
            if request.method!='GET' and not secrets.compare_digest(request.headers.get('x-order-csrf',''),csrf):
                return Response('Reload the order page before making changes.',status_code=403)
            response=await call_next(request)
            response.headers['Cache-Control']='no-store'
            response.headers['Referrer-Policy']='no-referrer'
            response.headers['X-Content-Type-Options']='nosniff'
            return response
        return await call_next(request)

    @app.get('/orders',response_class=HTMLResponse)
    async def workspace(request:Request):
        config=store.settings(); esc=html.escape
        base=request.headers.get('x-ingress-path','').rstrip('/')
        if base and not re.fullmatch(r'/[A-Za-z0-9_/-]+',base): raise HTTPException(400,'Invalid ingress path')
        rows=[]
        for row in store.list_orders():
            if config.get('results_hidden'): continue
            active=config.get('active_packing_ids')
            if active is not None and (row['shop']!=config['shop_id'] or row['source_id'] not in active): continue
            payload=row['payload']; items=payload.get('items',[])
            summary='; '.join(f"{i['quantity']} × {i['title']} — {i.get('variant','')} (SKU {i.get('sku','')})" for i in items)
            address=payload.get('address',{})
            delivery=', '.join(str(address.get(k,'')) for k in ('firstName','lastName','address1','city','zip'))
            tracking='; '.join(f"{t['carrier']}: {t['number']}" for t in row['tracking'])
            rows.append('<tr>'+''.join('<td>'+esc(str(v))+'</td>' for v in
                (row['source_id'],row['state'],summary,delivery,payload.get('total',''),row['message'],tracking))+'</tr>')
        try: domain=core.get_credentials('shopify').get('shop_domain','')
        except Exception: domain=''
        boot=json.dumps({'csrf':csrf,'base':base,'instance':instance},ensure_ascii=True).replace('<','\\u003c')
        values={k:esc(str(config[k])) for k in ('shop_id','shop_name','target_shop')}
        return HTMLResponse('''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>TikTok order imports</title><style>body{font:16px system-ui;background:#f3f5fa;color:#18213b;margin:24px}main{max-width:1400px;margin:auto}section{background:white;padding:24px;margin:16px 0;border-radius:16px}input,textarea,button{font:inherit;padding:10px;margin:5px}label{display:block}textarea{width:95%;height:80px}button{cursor:pointer;background:#253e80;color:white;border:0;border-radius:7px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:12px;border-bottom:1px solid #ddd;vertical-align:top}iframe{width:100%;height:720px;border:0}.scroll{overflow:auto}#status{white-space:pre-wrap}</style></head><body><main>
        '''+workspace_navigation('orders',base)+'''<h1>TikTok orders → Shopify</h1>
        <p>Order-only beta. Paid, seller-fulfilled orders become physical Shopify orders for postage labels. No catalogue matching.</p>
        <section><h2>Connection and controls</h2><p id="status">'''+esc(config['last_message'])+'''</p><p id="last-success">Last completed scan: not recorded yet.</p>
        <p>Connected Shopify: <strong>'''+esc(domain or 'Not connected')+'''</strong>. Tracking return is manual in this beta.</p>
        <label>TikTok shop name <input id="shop_name" value="'''+values['shop_name']+'''"></label>
        <label>TikTok shop ID <input id="shop_id" value="'''+values['shop_id']+'''"></label>
        <label>Verified Shopify destination <input id="target_shop" value="'''+values['target_shop']+'''" placeholder="your-shop.myshopify.com"></label>
        <label>Actual item weights in grams: JSON mapping of TikTok SKU ID to weight<textarea id="weights">'''+esc(json.dumps(config['weights'],indent=2))+'''</textarea></label>
        <label>Carrier names: JSON mapping from Shopify carrier to TikTok carrier<textarea id="carriers">'''+esc(json.dumps(config['carriers'],indent=2))+'''</textarea></label>
        <label><input id="enabled" type="checkbox" '''+('checked' if config['enabled'] else '')+'''>Import new orders every five minutes</label>
        <button onclick="save()">Save settings</button><button onclick="act('scan')">Scan and preview</button><button id="import-now" onclick="act('import')">Import TikTok orders now</button><button onclick="act('browser/start')">Start TikTok browser</button><button onclick="location.reload()">Refresh orders</button><p id="action-status" role="status"></p>
        <p>Start the browser, sign in below, save the verified account and actual weights, then preview before enabling imports. Session expiry pauses imports until you sign in again.</p></section>
        <section><h2>TikTok browser</h2><p>Sign in here on this Home Assistant host. Your browser session stays in the app’s private configuration.</p>
        <iframe title="TikTok sign in" src="'''+esc(base)+'''/orders/desktop/vnc.html?autoconnect=true&amp;reconnect=true&amp;reconnect_delay=3000&amp;resize=scale&amp;path='''+quote(base+'/orders/desktop/websockify?token='+csrf,safe='')+'''"></iframe></section>
        <section><h2>Import preview and review</h2><p>Unknown weights, masked addresses, discounts that do not reconcile, cancelled orders and multiple parcels need review. No labels are purchased automatically.</p><div class="scroll"><table><thead><tr><th>TikTok order</th><th>Status</th><th>Items</th><th>Delivery</th><th>GBP</th><th>Review</th><th>Tracking</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table></div></section>
        </main><script>const cfg='''+boot+''';'''+Path(__file__).with_name('order_feedback.js').read_text(encoding='utf-8')+'''</script></body></html>''')

    @app.post('/orders/settings')
    async def configure(request:Request):
        value=await request.json()
        if set(value)!={'shop_id','shop_name','target_shop','weights','carriers','enabled'}: raise HTTPException(400,'Invalid settings')
        if not re.fullmatch(r'\d{5,30}',str(value['shop_id'])) or not isinstance(value['shop_name'],str) or not 1<=len(value['shop_name'])<=100:
            raise HTTPException(400,'Enter the verified TikTok shop name and ID')
        if type(value['enabled']) is not bool: raise HTTPException(400,'Invalid import switch')
        if not isinstance(value['weights'],dict) or any(not re.fullmatch(r'\d{5,30}',k) or type(v) is not int or not 1<=v<=100000 for k,v in value['weights'].items()):
            raise HTTPException(400,'Weights must map SKU IDs to actual grams')
        if not isinstance(value['carriers'],dict) or any(not isinstance(k,str) or not isinstance(v,str) or not k.strip() or not v.strip() for k,v in value['carriers'].items()):
            raise HTTPException(400,'Invalid carrier mapping')
        domain=core.get_credentials('shopify').get('shop_domain','')
        if not domain or value['target_shop']!=domain: raise HTTPException(400,'Destination must match connected Shopify store')
        old=store.settings()
        if old['shop_id'] and value['shop_id']!=old['shop_id']: raise HTTPException(400,'A source-shop change requires a separate installation')
        if old['target_shop'] and value['target_shop']!=old['target_shop']: raise HTTPException(400,'A destination change requires a separate installation')
        changed=any(value[k]!=old[k] for k in ('shop_id','shop_name','target_shop','weights','carriers'))
        if value['enabled']:
            if changed or not old.get('preview_verified'): raise HTTPException(400,'Save settings and complete a successful preview before enabling imports')
            try:
                await OrderShopify(client_factory(core.get_credentials('shopify'))).check_scopes()
            except OrderProblem as exc:
                raise HTTPException(400,str(exc)) from exc
        stamp=datetime.now(timezone.utc).isoformat()
        store.configure(**value,settings_saved_at=stamp,preview_verified=old.get('preview_verified',False) and not changed)
        return {'ok':True,'saved_at':stamp}

    @app.post('/orders/scan')
    async def scan():
        if run_lock.locked(): raise HTTPException(409,'An order scan is already running; follow live progress above')
        store.configure(last_message='Preview requested…')
        schedule(cycle(dry=True)); return {'started':True}

    @app.post('/orders/import')
    async def import_now():
        if run_lock.locked(): raise HTTPException(409,'An order scan is already running')
        if not store.settings().get('preview_verified'):
            raise HTTPException(400,'Save settings, scan and check the preview before the first import')
        store.configure(last_message='Manual import requested…')
        schedule(cycle(manual=True)); return {'started':True}

    @app.get('/orders/status')
    async def order_status():
        config=store.settings()
        return {'message':config['last_message'],'running':run_lock.locked(),'automatic':config['enabled'],
                'last_success_at':config.get('last_success_at'),'instance':instance,
                'latest_run':config.get('latest_run'),'settings_saved_at':config.get('settings_saved_at'),
                'results_hidden':config.get('results_hidden',False),
                'next_scan_seconds':next_scan_seconds(config['enabled'],run_lock.locked(),last_completed,time.monotonic())}

    @app.post('/orders/clear-results')
    async def clear_results():
        store.configure(results_hidden=True)
        return {'ok':True}

    @app.post('/orders/browser/start')
    async def start_browser():
        async def start():
            try:
                store.configure(last_message='Starting TikTok browser and checking its display connection…')
                if not await desktop_ready():
                    store.configure(last_message='Desktop viewer is unavailable. Check the Shop Sync log for Xvfb or x11vnc errors.'); return
                await asyncio.to_thread(browser.start)
                store.configure(last_message='Browser started. Sign in in the browser panel, then scan.')
            except Exception:
                store.configure(last_message='Browser unavailable. Check supported host architecture and Chromium sandbox support.')
        schedule(start()); return {'started':True}

    async def open_listing_browser():
        if run_lock.locked(): raise HTTPException(409,'An order scan is running. Wait for it to finish before opening the listing browser.')
        async with run_lock:
            if not await desktop_ready(): raise HTTPException(503,'The TikTok browser display is unavailable on this host.')
            try: return await asyncio.to_thread(browser.open_listing_editor)
            except OrderProblem as exc: raise HTTPException(400,str(exc))
            except Exception: raise HTTPException(503,'The TikTok listing browser could not be opened. Check the browser session and try again.')
    app.state.tiktok_open_listing_browser=open_listing_browser

    async def fill_listing_browser(listing,photos):
        from .tiktok_listing_form import transfer_listing
        if run_lock.locked(): raise HTTPException(409,'The TikTok browser is busy with an order scan or another listing. Try again when it finishes.')
        async with run_lock:
            if not await desktop_ready(): raise HTTPException(503,'The TikTok browser display is unavailable on this host.')
            work=asyncio.create_task(asyncio.to_thread(transfer_listing,browser,listing,photos))
            try:
                # Cancelling a request does not stop Selenium's worker thread.
                # Keep the browser lock until the worker actually finishes.
                try: return await asyncio.shield(work)
                except asyncio.CancelledError:
                    try: await work
                    finally: raise
            except (ValueError,OrderProblem) as exc: raise HTTPException(400,str(exc))
            except Exception: raise HTTPException(503,'TikTok transfer stopped. Review the browser form before trying again. Shop Sync has not submitted it.')
    app.state.tiktok_fill_listing_browser=fill_listing_browser

    @app.get('/orders/desktop/{path:path}')
    async def desktop(path:str):
        if '..' in path or path.startswith('/'): raise HTTPException(400)
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                result=await client.get('http://127.0.0.1:6080/'+path)
            return Response(result.content,status_code=result.status_code,media_type=result.headers.get('content-type'))
        except httpx.HTTPError: return Response('Browser panel unavailable on this host.',status_code=503)

    @app.websocket('/orders/desktop/websockify')
    async def desktop_socket(websocket:WebSocket):
        if not websocket.client or not ingress_peer(websocket.client.host):
            await websocket.close(code=1008); return
        # noVNC sends token as a websocket query value; no cross-site cookies alone suffice.
        if not secrets.compare_digest(websocket.query_params.get('token',''),csrf):
            await websocket.close(code=1008); return
        import websockets
        await websocket.accept(subprotocol='binary' if 'binary' in websocket.headers.get('sec-websocket-protocol','') else None)
        try:
            async with websockets.connect('ws://127.0.0.1:6080/websockify') as upstream:
                async def incoming():
                    while True:
                        msg=await websocket.receive()
                        if msg['type']=='websocket.disconnect': return
                        await upstream.send(msg.get('bytes') if msg.get('bytes') is not None else msg.get('text',''))
                async def outgoing():
                    async for msg in upstream:
                        if isinstance(msg,bytes): await websocket.send_bytes(msg)
                        else: await websocket.send_text(msg)
                bridges=[asyncio.create_task(incoming()),asyncio.create_task(outgoing())]
                try:
                    done,_=await asyncio.wait(bridges,return_when=asyncio.FIRST_COMPLETED)
                    for task in done: task.result()
                finally:
                    for task in bridges: task.cancel()
                    await asyncio.gather(*bridges,return_exceptions=True)
        except WebSocketDisconnect: pass
        except Exception as exc:
            logging.getLogger(__name__).warning('Desktop viewer connection ended (%s)',type(exc).__name__)
        finally:
            with contextlib.suppress(Exception): await websocket.close()
    return store
