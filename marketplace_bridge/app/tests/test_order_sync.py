import pytest
from app.order_sync import OrderSync
from app.order_store import OrderStore
from app.security import SecretBox
from app.tests.test_orders import sample


class Shopify:
    def __init__(self): self.created=[]; self.existing=None; self.fail=False
    async def find(self, order_id):
        if self.fail: raise RuntimeError('query failed')
        return self.existing
    async def create(self,order):
        self.created.append(order)
        self.existing={'id':'gid://shopify/Order/123','cancelledAt':None,'displayFinancialStatus':'PAID',
                       'displayFulfillmentStatus':'UNFULFILLED','totalPriceSet':{'shopMoney':{'amount':order.total,'currencyCode':order.currency}}}
        return self.existing


@pytest.fixture
def setup(tmp_path):
    db=OrderStore(tmp_path/'orders.db',SecretBox.from_file(tmp_path/'key'))
    api=Shopify()
    return db,api,OrderSync(db,api)


@pytest.mark.asyncio
async def test_native_import_is_detected_and_not_duplicated(setup):
    db,api,sync=setup; api.existing={'id':'gid://shopify/Order/1020','cancelledAt':None}
    await sync.import_order(sample(),writes=True)
    assert api.created==[]
    assert db.get(sample().shop_id,sample().order_id)['shopify_id']==api.existing['id']


@pytest.mark.asyncio
async def test_repeat_import_and_dry_run_do_not_duplicate(setup):
    db,api,sync=setup
    await sync.import_order(sample(),writes=False)
    assert not api.created
    await sync.import_order(sample(),writes=True)
    await sync.import_order(sample(),writes=True)
    assert len(api.created)==1


@pytest.mark.asyncio
async def test_query_failure_never_means_create(setup):
    db,api,sync=setup; api.fail=True
    await sync.import_order(sample(),writes=True)
    assert not api.created
    assert db.get(sample().shop_id,sample().order_id)['state']=='review'


@pytest.mark.asyncio
async def test_ambiguous_create_reconciles_without_second_create(setup):
    db,api,sync=setup
    create=api.create
    async def lost_response(order):
        await create(order)
        raise TimeoutError('response lost')
    api.create=lost_response
    await sync.import_order(sample(),writes=True)
    assert db.get(sample().shop_id,sample().order_id)['state']=='uncertain'
    await sync.import_order(sample(),writes=True)
    assert len(api.created)==1


@pytest.mark.asyncio
async def test_unresolved_ambiguous_create_never_blindly_retries(setup):
    db,api,sync=setup
    db.record(sample(),'uncertain','Response lost')
    await sync.import_order(sample(),writes=True)
    assert not api.created


@pytest.mark.asyncio
async def test_uncertain_creation_with_mismatched_total_stays_in_review(setup):
    db,api,sync=setup; order=sample()
    db.record(order,'uncertain','Response lost')
    api.existing={'id':'gid://shopify/Order/123','cancelledAt':None,'displayFinancialStatus':'PAID',
                  'displayFulfillmentStatus':'UNFULFILLED','totalPriceSet':{'shopMoney':{'amount':'7.00','currencyCode':'GBP'}}}
    await sync.import_order(order,writes=True)
    row=db.get(order.shop_id,order.order_id)
    assert row['state']=='review' and 'differs' in row['message']
    assert row['shopify_id']==api.existing['id'] and not api.created
    await sync.import_order(order,writes=True)
    assert db.get(order.shop_id,order.order_id)['state']=='review'


@pytest.mark.asyncio
async def test_uncertain_tracking_never_blindly_submits_again(setup):
    db,api,sync=setup; order=sample()
    db.configure(carriers={'Royal Mail':'Royal Mail'})
    db.record(order,'tracking_uncertain','Lost browser response','gid://shopify/Order/123')
    async def tracking(_): return {'cancelledAt':None,'shipments':[dict(number='AB123GB',company='Royal Mail',complete=True)]}
    api.tracking=tracking
    class Browser:
        def submit_tracking(self,*args): raise AssertionError('must not submit twice')
    await sync.sync_tracking(order,Browser(),writes=True)
    assert db.get(order.shop_id,order.order_id)['state']=='tracking_uncertain'
