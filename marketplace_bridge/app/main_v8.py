from fastapi.responses import HTMLResponse
from . import main as core
from . import main_v7 as v7
from .main_v5 import _shopify_client, _drop_route
from .order_web import mount_orders
from .listing_web import mount_listings
from .workspace_navigation import workspace_navigation
import re

app=v7.app
app.version='0.0.35-beta10'
order_store=mount_orders(app,core,_shopify_client)
listing_store=mount_listings(app,core,_shopify_client)
_drop_route('/','GET')

@app.get('/',response_class=HTMLResponse)
def dashboard():
    page=v7.dashboard().body.decode('utf-8')
    page=re.sub(r'(<main\b[^>]*>)',lambda match:match.group(1)+workspace_navigation('dashboard'),page,count=1)
    return HTMLResponse(page)
