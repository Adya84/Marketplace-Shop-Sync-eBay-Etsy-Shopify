let busy=false, dirty=false, saving=false, deadline=null, lastResult=null, editRevision=0;
const byId=id=>document.getElementById(id);
const stamp=value=>new Date(value).toLocaleString('en-GB',{timeZone:'Europe/London'});
const saveNotice=document.createElement('p');
saveNotice.id='save-status';saveNotice.setAttribute('role','status');
byId('enabled').parentElement.after(saveNotice);
const summary=document.createElement('p');summary.id='scan-result';summary.setAttribute('role','status');
const countdown=document.createElement('p');countdown.id='next-scan';
byId('last-success').after(summary,countdown);
const clear=document.createElement('button');clear.textContent='Clear displayed results';clear.type='button';
const table=document.querySelector('table');table.parentElement.before(clear);
clear.onclick=async()=>{try{await send('clear-results');table.querySelector('tbody').replaceChildren();summary.textContent='Displayed results cleared. Import records and duplicate protection are retained.'}catch(e){byId('action-status').textContent=e.message}};
for(const id of ['shop_name','shop_id','target_shop','weights','carriers','enabled']){
 byId(id).addEventListener('input',()=>{editRevision++;dirty=true;saveNotice.textContent='Unsaved changes';saveNotice.style.color='#924000'});
}
async function send(path,body){
 const r=await fetch(cfg.base+'/orders/'+path,{method:'POST',headers:{'content-type':'application/json','x-order-csrf':cfg.csrf},body:JSON.stringify(body||{})});
 const text=await r.text();let data;try{data=JSON.parse(text)}catch(e){}
 if(!r.ok)throw Error(data?.detail||text||'Request failed');
 return data;
}
async function refreshResults(){
 const r=await fetch(cfg.base+'/orders',{cache:'no-store'});if(!r.ok)throw Error('Could not refresh scan details');
 const doc=new DOMParser().parseFromString(await r.text(),'text/html');
 table.querySelector('tbody').replaceChildren(...doc.querySelector('tbody').childNodes);
}
async function status(){try{
 const r=await fetch(cfg.base+'/orders/status',{cache:'no-store'});if(!r.ok)throw Error('Status unavailable');
 const s=await r.json();if(s.instance!==cfg.instance){if(!dirty&&!saving)location.reload();else byId('action-status').textContent='Shop Sync restarted. Copy your unsaved edits before reloading.';return}
 byId('import-now').disabled=s.running;
 byId('status').textContent=(s.running?'Scan in progress. ':'')+s.message;
 byId('last-success').textContent='Last completed scan: '+(s.last_success_at?stamp(s.last_success_at):'not recorded yet');
 deadline=s.next_scan_seconds===null?null:Date.now()+s.next_scan_seconds*1000;
 countdown.dataset.state=s.running?'Scan in progress':s.automatic?'Scheduled':'Automatic import off';tick();
 if(!dirty&&!saving&&s.settings_saved_at&&!saveNotice.dataset.error)saveNotice.textContent='Settings saved at '+stamp(s.settings_saved_at);
 const run=s.latest_run;
 if(run&&!s.results_hidden){
  if(run.state==='running')summary.textContent='Scan in progress — '+(run.mode==='preview'?'preview only':'importing orders');
  else{const c=run.counts||{};summary.textContent=(run.state==='failed'?'Scan failed at ':'Scan completed at ')+stamp(run.completed_at)+'. '+(run.state==='failed'?run.message+'. ':'')+(c.checked||0)+' orders checked · '+(c.imported||0)+' imported · '+(c.existing||0)+' already in Shopify · '+(c.ready||0)+' ready to import · '+(c.review||0)+' need review · '+(c.failed||0)+' failed'+(run.mode==='preview'?' — Preview only; no orders imported.':'');}
 }
 const key=JSON.stringify([run?.completed_at,s.results_hidden]);
 if(key!==lastResult&&!s.running){await refreshResults();lastResult=key}
 byId('action-status').dataset.connectionError='';
 }catch(e){byId('action-status').textContent='Could not read Shop Sync status. Connection lost; scan progress is unverified.';deadline=null;countdown.dataset.state='Next scan time unavailable';tick()}
}
function tick(){if(deadline===null){countdown.textContent=countdown.dataset.state||'Next scan time unavailable';return}const n=Math.max(0,Math.ceil((deadline-Date.now())/1000));countdown.textContent=n?'Next scan in '+Math.floor(n/60)+':'+String(n%60).padStart(2,'0'):'Next scan due — waiting to start'}
async function act(path){if(busy)return;busy=true;byId('action-status').textContent='Sending request…';try{await send(path);byId('action-status').textContent=path==='import'?'Import request accepted.':path==='scan'?'Preview request accepted.':'Browser start requested.';await status()}catch(e){byId('action-status').textContent=e.message}finally{busy=false}}
async function save(){if(saving)return;const submittedRevision=editRevision;saving=true;saveNotice.textContent='Saving…';saveNotice.style.color='#18213b';try{
 let weights,carriers;try{weights=JSON.parse(byId('weights').value);carriers=JSON.parse(byId('carriers').value)}catch(e){throw Error('Invalid weights or carrier JSON. Changes were not saved.')}
 const data=await send('settings',{shop_name:byId('shop_name').value,shop_id:byId('shop_id').value,target_shop:byId('target_shop').value,weights,carriers,enabled:byId('enabled').checked});
 dirty=editRevision!==submittedRevision;delete saveNotice.dataset.error;saveNotice.textContent=dirty?'Earlier settings saved; newer changes are unsaved.':'Settings saved at '+stamp(data.saved_at);saveNotice.style.color=dirty?'#924000':'#166534';
 }catch(e){saveNotice.dataset.error='true';saveNotice.textContent='Not saved: '+e.message;saveNotice.style.color='#b91c1c'}finally{saving=false;await status()}}
status();setInterval(status,3000);setInterval(tick,1000);
