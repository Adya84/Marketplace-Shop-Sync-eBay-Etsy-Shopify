"""Order-only beta workspace. All routes require HA Ingress's socket peer."""
import asyncio
import contextlib
import html
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import quote
import httpx
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from .order_browser import TikTokBrowser
from .order_models import SourceOrder, OrderProblem
from .order_store import OrderStore
from .order_shopify import OrderShopify
from .order_sync import OrderSync


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
    browser=TikTokBrowser(core.settings.data_dir/'tiktok-browser',store.settings,
                         lambda message:store.configure(last_message=message))
    csrf=secrets.token_urlsafe(32)
    run_lock=asyncio.Lock()
    last_completed=None
    tasks=set()
    previous=app.router.lifespan_context

    async def cycle(dry=False,manual=False):
        nonlocal last_completed
        if run_lock.locked(): return
        async with run_lock:
            stage='Shopify connection'
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
                known=store.list_orders(10000)
                linked=[r['source_id'] for r in known if r['shop']==config['shop_id'] and
                        (r['shopify_id'] or r['state'] in {'uncertain','claimed'})]
                sync=OrderSync(store,shopify)
                ready=0; failures=0
                pending=list(dict.fromkeys([*ids,*linked]))
                for position,order_id in enumerate(pending,1):
                    stage='order verification'
                    store.configure(last_message=f'Checking order {position} of {len(pending)}…')
                    try:
                        order=await asyncio.to_thread(browser.detail,order_id)
                    except Exception as exc:
                        # Retain a durable review record without logging customer content.
                        old=store.get(config['shop_id'],order_id)
                        payload=old['payload'] if old else dict(shop_id=config['shop_id'],order_id=order_id,
                            status='Unknown',currency='GBP',total='0.00',shipping='0.00',address={},items=[],seller_fulfilled=False)
                        failures+=1
                        reason=str(exc) if isinstance(exc,OrderProblem) else type(exc).__name__
                        store.source_failure(SourceOrder(**payload),reason)
                        continue
                    # Never backfill already-dispatched historical orders.
                    if order_id not in linked and order.status not in {'Awaiting packing','Awaiting shipment'}: continue
                    await sync.import_order(order,writes=writes)
                    try:
                        order.validate()
                        if store.get(order.shop_id,order_id)['state'] in {'preview','linked'}: ready+=1
                    except OrderProblem: pass
                    # Tracking submission remains manual in this beta; show verified data only.
                    await sync.sync_tracking(order,browser,writes=False)
                # Detail failures remain durable review rows and never reach
                # creation. They must not block independently validated orders.
                if dry: store.configure(preview_verified=ready>0)
                store.configure(last_message=f'Scan complete: {len(ids)} shipping-queue orders inspected. '+
                                ('Preview only.' if not writes else 'Import run finished.')+
                                (f' {failures} orders need source review.' if failures else ''))
            except OrderProblem as exc:
                store.configure(last_message=str(exc))
            except Exception as exc:
                # Never expose raw driver/HTTP errors: they may contain buyer
                # information, request headers or session capabilities.
                store.configure(last_message=f'Scan stopped during {stage}: {type(exc).__name__}.')
            finally: last_completed=time.monotonic()

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
            except OrderProblem as exc: store.configure(last_message=str(exc))
            except Exception as exc:
                store.configure(last_message=f'Between-check browser refresh failed: {type(exc).__name__}; next check will retry.')

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
            payload=row['payload']; items=payload.get('items',[])
            summary='; '.join(f"{i['quantity']} × {i['title']} — {i.get('variant','')} (SKU {i.get('sku','')})" for i in items)
            address=payload.get('address',{})
            delivery=', '.join(str(address.get(k,'')) for k in ('firstName','lastName','address1','city','zip'))
            tracking='; '.join(f"{t['carrier']}: {t['number']}" for t in row['tracking'])
            rows.append('<tr>'+''.join('<td>'+esc(str(v))+'</td>' for v in
                (row['source_id'],row['state'],summary,delivery,payload.get('total',''),row['message'],tracking))+'</tr>')
        try: domain=core.get_credentials('shopify').get('shop_domain','')
        except Exception: domain=''
        boot=json.dumps({'csrf':csrf,'base':base},ensure_ascii=True).replace('<','\\u003c')
        values={k:esc(str(config[k])) for k in ('shop_id','shop_name','target_shop')}
        return HTMLResponse('''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>TikTok order imports</title><style>body{font:16px system-ui;background:#f3f5fa;color:#18213b;margin:24px}main{max-width:1400px;margin:auto}section{background:white;padding:24px;margin:16px 0;border-radius:16px}input,textarea,button{font:inherit;padding:10px;margin:5px}label{display:block}textarea{width:95%;height:80px}button{cursor:pointer;background:#253e80;color:white;border:0;border-radius:7px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:12px;border-bottom:1px solid #ddd;vertical-align:top}iframe{width:100%;height:720px;border:0}.scroll{overflow:auto}#status{white-space:pre-wrap}</style></head><body><main>
        <a href="'''+esc(base)+'''/">← Shop Sync</a><h1>TikTok orders → Shopify</h1>
        <p>Order-only beta. Paid, seller-fulfilled orders become physical Shopify orders for postage labels. No catalogue matching.</p>
        <section><h2>Connection and controls</h2><p id="status">'''+esc(config['last_message'])+'''</p>
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
        <iframe title="TikTok sign in" src="'''+esc(base)+'''/orders/desktop/vnc.html?autoconnect=true&amp;resize=scale&amp;path='''+quote(base+'/orders/desktop/websockify?token='+csrf,safe='')+'''"></iframe></section>
        <section><h2>Import preview and review</h2><p>Unknown weights, masked addresses, discounts that do not reconcile, cancelled orders and multiple parcels need review. No labels are purchased automatically.</p><div class="scroll"><table><thead><tr><th>TikTok order</th><th>Status</th><th>Items</th><th>Delivery</th><th>GBP</th><th>Review</th><th>Tracking</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table></div></section>
        </main><script>const cfg='''+boot+''';let busy=false;async function status(){try{const r=await fetch(cfg.base+'/orders/status',{cache:'no-store'});if(!r.ok)return;const s=await r.json();document.getElementById('import-now').disabled=s.running;document.getElementById('status').textContent=(s.running?'Working… ':'')+s.message+' '+(s.automatic?'Automatic import is on (5 minute interval).':'Automatic import is off.')}catch(e){}}async function send(path,body){const r=await fetch(cfg.base+'/orders/'+path,{method:'POST',headers:{'content-type':'application/json','x-order-csrf':cfg.csrf},body:JSON.stringify(body||{})});const text=await r.text();if(!r.ok){let detail=text;try{detail=JSON.parse(text).detail||text}catch(e){}document.getElementById('action-status').textContent=detail;return false}await status();return true}async function act(path){if(busy)return;busy=true;document.getElementById('action-status').textContent='Sending request…';try{if(await send(path)){document.getElementById('action-status').textContent=path==='import'?'Import request accepted. Follow live progress above.':path==='scan'?'Preview request accepted. Follow live progress above.':'Browser start requested.';await status()}}catch(e){document.getElementById('action-status').textContent='Could not reach Shop Sync. Reload this page and try again.'}finally{busy=false}}async function save(){try{await send('settings',{shop_name:document.getElementById('shop_name').value,shop_id:document.getElementById('shop_id').value,target_shop:document.getElementById('target_shop').value,weights:JSON.parse(document.getElementById('weights').value),carriers:JSON.parse(document.getElementById('carriers').value),enabled:document.getElementById('enabled').checked});await status()}catch(e){document.getElementById('status').textContent='Check the JSON settings.'}}status();setInterval(status,3000)</script></body></html>''')

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
        store.configure(**value,preview_verified=old.get('preview_verified',False) and not changed)
        return {'ok':True}

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
        return {'message':config['last_message'],'running':run_lock.locked(),'automatic':config['enabled']}

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
            store.configure(last_message='Desktop connection failed ('+type(exc).__name__+'). Check the Shop Sync log for display-service errors.')
        finally:
            with contextlib.suppress(Exception): await websocket.close()
    return store
