"""Navigation among distinct Shop Sync pages, preserving HA Ingress paths."""
import html
import re


def workspace_navigation(active,base='.'):
    if base!='.' and not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)*',base):
        raise ValueError('Invalid Shop Sync base path')
    links=[]
    for key,path,label in (('dashboard','/','Dashboard'),('listings','/listing-tool','Listing tool'),('orders','/orders','Order imports')):
        current=' aria-current="page"' if active==key else ''
        background='#246342' if active==key else '#edf2eb'
        color='white' if active==key else '#294630'
        links.append(f'<a href="{html.escape(base+path,quote=True)}"{current} style="padding:10px 16px;border-radius:9px;text-decoration:none;font:600 14px system-ui;background:{background};color:{color}">{label}</a>')
    return '<nav aria-label="Shop Sync pages" style="display:flex;flex-wrap:wrap;gap:8px;margin:16px 0">'+''.join(links)+'</nav>'
