"""Marketplace-neutral validation and explicit publish orchestration."""
import copy
import hashlib
import json
from decimal import Decimal, InvalidOperation
import httpx

MARKETS=('etsy','ebay','tiktok','shopify')
TITLE_LIMITS={'etsy':140,'ebay':80,'tiktok':255,'shopify':255}


def effective_listing(master, destination, defaults):
    result=copy.deepcopy(master)
    config=master.get('destinations',{}).get(destination,{})
    overrides=config.get('overrides') or {}
    for key in ('title','description','tags'):
        if overrides.get(key) not in (None,''): result[key]=copy.deepcopy(overrides[key])
    if overrides.get('price') not in (None,''):
        for variant in result.get('variants',[]): variant['price']=str(overrides['price'])
    if overrides.get('prices'):
        for variant in result.get('variants',[]):
            if variant['sku'] in overrides['prices']: variant['price']=str(overrides['prices'][variant['sku']])
    result['destination']=destination
    result['settings']={**copy.deepcopy(defaults),**copy.deepcopy(config.get('settings') or {})}
    return result


def validate_listing(listing):
    errors=[]; destination=listing['destination']; variants=listing.get('variants') or []
    title=str(listing.get('title') or '').strip()
    if not title: errors.append('Add a title.')
    if len(title)>TITLE_LIMITS[destination]: errors.append(f'{destination.title()} title must be {TITLE_LIMITS[destination]} characters or fewer; add a shorter shop title.')
    if not str(listing.get('description') or '').strip(): errors.append('Add a description.')
    if listing.get('currency') not in ('GBP','USD','EUR','CAD','AUD'): errors.append('Choose a supported currency.')
    if not listing.get('photos'): errors.append('Add at least one photo.')
    if len(listing.get('photos') or [])>({'etsy':20,'ebay':24,'tiktok':9,'shopify':250}[destination]): errors.append(f'Too many photos for {destination.title()}.')
    if not variants: errors.append('Add a price, stock quantity and SKU.')
    seen=set(); combinations=set(); names=None
    for variant in variants:
        sku=str(variant.get('sku') or '').strip()
        if not sku or sku.casefold() in seen: errors.append('Every variant needs a unique SKU.')
        seen.add(sku.casefold())
        try:
            price=Decimal(str(variant.get('price','')))
            if not price.is_finite() or price<=0: raise ValueError()
        except (InvalidOperation,ValueError): errors.append(f'{sku or "Variant"}: enter a price greater than zero.')
        quantity=variant.get('quantity')
        if isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<0: errors.append(f'{sku or "Variant"}: quantity must be a whole number of zero or more.')
        options=variant.get('options') or []
        current=tuple(str(o.get('name') or '').strip() for o in options)
        if any(not name for name in current) or len(set(current))!=len(current) or any(not str(o.get('value') or '').strip() for o in options): errors.append('Each variation needs an option name and value.')
        if names is not None and names!=current: errors.append('Use the same option names and order for every variant.')
        names=current
        key=tuple(str(o.get('value') or '').strip() for o in options)
        if key in combinations: errors.append('Two variants have the same option combination.')
        combinations.add(key)
    if destination=='etsy' and len(names or ())>2: errors.append('Etsy allows two variation options. Choose a compatible Etsy version before publishing; no variants will be dropped.')
    if destination=='shopify' and len(names or ())>3: errors.append('Shopify allows three variation options.')
    if destination=='etsy' and (len(listing.get('tags') or [])>13 or any(len(t)>20 for t in listing.get('tags') or [])): errors.append('Etsy tags need at most 13 entries, each 20 characters or fewer. Set Etsy tags in its shop section.')
    return list(dict.fromkeys(errors))


class ListingService:
    def __init__(self, store, writer_factory): self.store=store; self.writer_factory=writer_factory

    async def validate(self, master):
        output={}
        for destination in MARKETS:
            if not master.get('destinations',{}).get(destination,{}).get('enabled'): continue
            listing=effective_listing(master,destination,self.store.defaults(destination))
            errors=validate_listing(listing)
            try: errors+=await self.writer_factory(destination).validate(listing,listing['settings'])
            except ValueError as exc: errors.append(str(exc))
            except Exception: errors.append(f'Connect {destination.title()} and check its saved shop settings.')
            output[destination]=list(dict.fromkeys(errors))
        return output

    async def publish(self, identifier, owner=None, snapshot=None):
        owner=owner or self.store.claim(identifier)
        try:
            master=copy.deepcopy(snapshot) if snapshot is not None else self.store.get(identifier)
            # Snapshot all defaults before awaiting external calls or allowing edits.
            snapshots={d:effective_listing(master,d,self.store.defaults(d)) for d in MARKETS
                       if master.get('destinations',{}).get(d,{}).get('enabled')}
            for destination, listing in snapshots.items():
                previous=self.store.results(identifier).get(destination,{})
                payload={k:v for k,v in listing.items() if k not in ('revision','destinations','updated','results')}
                digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
                if previous.get('status')=='success' and previous.get('digest')==digest: continue
                if previous.get('status') in ('uncertain','sending'): continue
                errors=validate_listing(listing)
                try:
                    writer=self.writer_factory(destination)
                    errors+=await writer.validate(listing,listing['settings'])
                except ValueError as exc:
                    errors.append(str(exc))
                except Exception:
                    errors.append(f'Connect {destination.title()} and check its saved shop settings.')
                if errors:
                    self.store.result(identifier,destination,status='blocked',revision=master['revision'],message=' '.join(dict.fromkeys(errors)))
                    continue
                self.store.result(identifier,destination,status='sending',revision=master['revision'],digest=digest,message='Sending saved listing…')
                def checkpoint(mapping, d=destination): self.store.result(identifier,d,mapping=mapping)
                try:
                    result=await writer.publish(listing,listing['settings'],copy.deepcopy(previous.get('mapping') or {}),checkpoint)
                    if not result.get('id'): raise RuntimeError('Shop did not return a listing ID; check the shop before retrying.')
                    self.store.result(identifier,destination,status='success',mapping=result,revision=master['revision'],digest=digest,message=result.get('message') or result.get('state') or 'Submitted')
                except (ValueError, httpx.HTTPStatusError) as exc:
                    # A returned rejection is retryable, whereas transport loss is ambiguous.
                    status='uncertain' if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code>=500 else 'failed'
                    message=str(exc) if isinstance(exc,ValueError) else f'{destination.title()} rejected the request (HTTP {exc.response.status_code}). Check shop requirements and permissions.'
                    self.store.result(identifier,destination,status=status,message=message)
                except Exception:
                    self.store.result(identifier,destination,status='uncertain',message='The shop did not confirm completion. Check the shop and reconcile its listing ID before retrying.')
            return self.store.results(identifier)
        finally: self.store.release(identifier,owner)
