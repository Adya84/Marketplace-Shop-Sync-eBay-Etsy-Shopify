from fastapi.responses import HTMLResponse
from . import main as core
from . import main_v7 as v7
from .main_v5 import _shopify_client, _drop_route
from .order_web import mount_orders

app=v7.app
app.version='0.0.34-beta2'
order_store=mount_orders(app,core,_shopify_client)
_drop_route('/','GET')

@app.get('/',response_class=HTMLResponse)
def dashboard():
    page=v7.dashboard().body.decode('utf-8')
    return HTMLResponse(page.replace('</body>', '<a href="orders" style="position:fixed;right:24px;bottom:24px;padding:14px 22px;background:#263e80;color:white;border-radius:12px;z-index:1000">TikTok order imports · beta</a></body>'))
