"""Home Assistant Ingress-only listing editor and local media library."""
import asyncio
import json
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, Response
from .listing_connections import Connections
from .listing_store import ListingStore
from .listings import ListingService, MARKETS, effective_listing
from .tiktok_listing_form import prepare_plan
from .order_web import ingress_peer
from .workspace_navigation import workspace_navigation


async def bounded_body(request,limit):
    parts=[]; size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>limit: raise HTTPException(413,'This upload is too large.')
        parts.append(chunk)
    return b''.join(parts)


def clean_draft(value,photos):
    if not isinstance(value,dict): raise ValueError('Invalid listing data.')
    clean={key:value[key] for key in ('id','revision','title','description','currency','tags','photos','variants','destinations') if key in value}
    for key in ('title','description','currency'):
        if key in clean and not isinstance(clean[key],str): raise ValueError('Invalid '+key+'.')
    if len(clean.get('title',''))>1000 or len(clean.get('description',''))>50000: raise ValueError('Listing text is too long.')
    clean.setdefault('title',''); clean.setdefault('description',''); clean.setdefault('currency','GBP')
    for key in ('tags','photos','variants'):
        clean.setdefault(key,[])
        if not isinstance(clean[key],list): raise ValueError('Invalid '+key+'.')
    if len(clean['photos'])>250 or len(clean['variants'])>250 or len(clean['tags'])>100: raise ValueError('Too many listing entries.')
    if any(not isinstance(tag,str) or len(tag)>100 for tag in clean['tags']): raise ValueError('Invalid tags.')
    for name in clean['photos']:
        if not isinstance(name,str) or not re.fullmatch(r'[a-f0-9]{32}\.(jpg|png)',name) or not (photos/name).is_file(): raise ValueError('Upload each listing photo before saving.')
    for variant in clean['variants']:
        if not isinstance(variant,dict) or not isinstance(variant.get('sku'),str) or len(variant['sku'])>100: raise ValueError('Invalid variant SKU.')
        if not isinstance(variant.get('price'),(str,int,float)): raise ValueError('Invalid variant price.')
        options=variant.get('options') or []
        if not isinstance(options,list) or len(options)>5 or any(not isinstance(o,dict) or not isinstance(o.get('name'),str) or not isinstance(o.get('value'),str) for o in options): raise ValueError('Invalid variant options.')
    destinations=clean.setdefault('destinations',{})
    if not isinstance(destinations,dict) or any(d not in MARKETS for d in destinations): raise ValueError('Invalid destination shop.')
    for destination,config in destinations.items():
        if not isinstance(config,dict) or not isinstance(config.get('enabled',False),bool): raise ValueError('Invalid shop selection.')
        if not isinstance(config.get('overrides',{}),dict) or not isinstance(config.get('settings',{}),dict): raise ValueError('Invalid shop settings.')
    return clean


def mount_listings(app,core,shopify_factory):
    root=core.settings.data_dir
    photos=root/'listing-photos'; photos.mkdir(parents=True,exist_ok=True)
    store=ListingStore(root/'listings.db')
    connections=Connections(core,shopify_factory,photos)
    service=ListingService(store,connections.writer)
    csrf=secrets.token_urlsafe(32); tasks=set(); previous=app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with previous(application):
            try: yield
            finally:
                for task in tasks: task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
    app.router.lifespan_context=lifespan

    @app.middleware('http')
    async def protect(request:Request,call_next):
        if request.url.path in ('/listings','/listing-tool') or request.url.path.startswith('/listings/'):
            if not request.client or not ingress_peer(request.client.host): return Response('Open through Home Assistant Ingress.',status_code=403)
            if request.method not in ('GET','HEAD') and not secrets.compare_digest(request.headers.get('x-listing-csrf',''),csrf): return Response('Reload Listings before making changes.',status_code=403)
            response=await call_next(request)
            response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'})
            return response
        return await call_next(request)

    def listing(identifier):
        try: return store.get(identifier)
        except KeyError: raise HTTPException(404,'Listing not found.')

    async def body(request):
        try: return json.loads(await bounded_body(request,1024*1024))
        except (ValueError,UnicodeDecodeError): raise HTTPException(400,'Invalid listing data.')

    @app.get('/listings',response_class=HTMLResponse)
    @app.get('/listing-tool',response_class=HTMLResponse)
    async def editor(request:Request):
        base=request.headers.get('x-ingress-path','').rstrip('/')
        if base and not re.fullmatch(r'/[A-Za-z0-9_/-]+',base): raise HTTPException(400,'Invalid Ingress path.')
        page=Path(__file__).with_name('listing_editor.html').read_text(encoding='utf-8')
        page=page.replace('__WORKSPACE_NAV__',workspace_navigation('listings',base))
        viewer=getattr(app.state,'tiktok_browser_view_url',None)
        return HTMLResponse(page.replace('__LISTING_CONFIG__',json.dumps({'csrf':csrf,'base':base+'/listings/',
            'browser_view':viewer(base) if viewer else ''})))

    @app.post('/listings/api/tiktok/browser/open')
    async def open_tiktok_browser():
        opener=getattr(app.state,'tiktok_open_listing_browser',None)
        if opener is None: raise HTTPException(503,'Open Listing tool in the installed Shop Sync app to use its TikTok browser.')
        return await opener()

    @app.get('/listings/api/drafts')
    async def drafts(): return [{'id':row['id'],'title':row['title'],'revision':row['revision'],'updated':row['updated'],'photos':row.get('photos',[]),'results':store.results(row['id'])} for row in store.list()]

    @app.get('/listings/api/drafts/{identifier}')
    async def get_draft(identifier:str): return {**listing(identifier),'results':store.results(identifier)}

    @app.post('/listings/api/drafts')
    async def save(request:Request):
        try: return store.save(clean_draft(await body(request),photos))
        except ValueError as exc: raise HTTPException(400,str(exc))

    @app.post('/listings/api/drafts/{identifier}/validate')
    async def validate(identifier:str):
        value=listing(identifier)
        try: await connections.prepare()
        except Exception: pass
        return await service.validate(value)

    @app.post('/listings/api/drafts/{identifier}/tiktok/prepare')
    async def prepare_tiktok(identifier:str):
        value=listing(identifier)
        transfer=getattr(app.state,'tiktok_fill_listing_browser',None)
        if transfer is None: raise HTTPException(503,'Use the installed Shop Sync TikTok browser to transfer this listing.')
        previous=store.results(identifier).get('tiktok',{})
        if previous.get('mapping',{}).get('id') or previous.get('status') in ('uncertain','sending'):
            raise HTTPException(409,'This listing already has a TikTok submission or an unresolved result. Check the existing product instead of creating another.')
        snapshot=effective_listing(value,'tiktok',store.defaults('tiktok'))
        try:
            prepare_plan(snapshot,photos)
            owner=store.claim(identifier)
        except ValueError as exc: raise HTTPException(400,str(exc))
        store.result(identifier,'tiktok',status='preparing',revision=value['revision'],message='Transferring saved details to the TikTok browser. Not published.')
        async def run():
            try:
                result=await transfer(snapshot,photos)
                store.result(identifier,'tiktok',status='needs_review',message=result['message'])
            except asyncio.CancelledError:
                store.result(identifier,'tiktok',status='needs_review',message='Browser transfer was interrupted. Check the TikTok form before retrying. It has not been submitted by Shop Sync.')
                raise
            except (ValueError,HTTPException) as exc:
                store.result(identifier,'tiktok',status='blocked',message=str(exc.detail) if isinstance(exc,HTTPException) else str(exc))
            except Exception:
                store.result(identifier,'tiktok',status='needs_review',message='Browser transfer stopped. Review the partially filled TikTok form before retrying. No automatic submission was attempted.')
            finally: store.release(identifier,owner)
        task=asyncio.create_task(run()); tasks.add(task)
        def done(task):
            tasks.discard(task)
            if not task.cancelled(): task.exception()
        task.add_done_callback(done)
        return {'queued':True,'revision':value['revision'],'state':'preparing'}

    @app.post('/listings/api/drafts/{identifier}/publish')
    async def publish(identifier:str):
        value=listing(identifier)
        if not any(c.get('enabled') for c in value.get('destinations',{}).values()): raise HTTPException(400,'Choose at least one shop.')
        try:
            await connections.prepare()
        except Exception:
            # An eBay refresh failure must not prevent other shops from sending.
            pass
        try: owner=store.claim(identifier)
        except ValueError as exc: raise HTTPException(409,str(exc))
        task=asyncio.create_task(service.publish(identifier,owner=owner,snapshot=value)); tasks.add(task)
        def done(task):
            tasks.discard(task)
            if not task.cancelled(): task.exception()
        task.add_done_callback(done)
        return {'queued':True,'revision':value['revision']}

    @app.get('/listings/api/drafts/{identifier}/results')
    async def results(identifier:str):
        listing(identifier)
        with store.connect() as db: busy=db.execute('SELECT 1 FROM listing_locks WHERE listing_id=?',(identifier,)).fetchone()
        return {'results':store.results(identifier),'busy':bool(busy)}

    @app.post('/listings/api/drafts/{identifier}/reconcile/{destination}')
    async def reconcile(identifier:str,destination:str,request:Request):
        listing(identifier)
        if destination not in MARKETS: raise HTTPException(400,'Unknown shop.')
        value=await body(request); remote=str(value.get('id') or '').strip()
        if not re.fullmatch(r'(gid://shopify/Product/)?[0-9]+',remote): raise HTTPException(400,'Enter the existing shop listing ID.')
        if destination=='shopify' and remote.isdigit(): remote='gid://shopify/Product/'+remote
        owner=store.claim(identifier)
        try: store.result(identifier,destination,status='failed',mapping={'id':remote},message='Linked existing listing. Check settings, then press Update all.')
        finally: store.release(identifier,owner)
        return {'linked':True}

    @app.get('/listings/api/defaults')
    async def defaults():
        connected={}
        for destination in MARKETS:
            if destination=='tiktok':
                connected[destination]=connections.tiktok_browser_publisher is not None
                continue
            try: connected[destination]=bool(core.get_credentials(destination))
            except Exception: connected[destination]=False
        return {'defaults':{d:store.defaults(d) for d in MARKETS},'connected':connected}

    @app.post('/listings/api/defaults/{destination}')
    async def save_defaults(destination:str,request:Request):
        if destination not in MARKETS: raise HTTPException(400,'Unknown shop.')
        value=await body(request)
        if not isinstance(value,dict): raise HTTPException(400,'Invalid shop settings.')
        store.save_defaults(destination,value)
        return {'saved':True}

    @app.get('/listings/api/options/{destination}/{kind}')
    async def options(destination:str,kind:str,category:str=''):
        if destination not in MARKETS: raise HTTPException(400,'Unknown shop.')
        try:
            await connections.prepare()
            return await connections.options(destination,kind,category)
        except Exception: raise HTTPException(400,'Could not load shop settings. Check the shop connection and permissions on the dashboard.')

    @app.post('/listings/api/photos')
    async def upload(request:Request):
        # Raw body is streamed with a hard bound, before multipart parsing can
        # spool unbounded untrusted files to disk.
        mime=request.headers.get('content-type','').split(';')[0]
        if mime not in ('image/jpeg','image/png'): raise HTTPException(400,'Choose a JPEG or PNG photo.')
        data=await bounded_body(request,10*1024*1024)
        if mime=='image/png' and not data.startswith(b'\x89PNG\r\n\x1a\n'): raise HTTPException(400,'Invalid PNG photo.')
        if mime=='image/jpeg' and not (data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9')): raise HTTPException(400,'Invalid JPEG photo.')
        name=secrets.token_hex(16)+('.png' if mime=='image/png' else '.jpg')
        (photos/name).write_bytes(data)
        return {'name':name}

    @app.get('/listings/photos/{name}')
    async def photo(name:str):
        if not re.fullmatch(r'[a-f0-9]{32}\.(jpg|png)',name) or not (photos/name).is_file(): raise HTTPException(404,'Photo not found.')
        return FileResponse(photos/name,media_type='image/png' if name.endswith('.png') else 'image/jpeg')

    return store
