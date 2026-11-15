const byId=id=>document.getElementById(id);
async function send(path,body){
 const r=await fetch(cfg.base+'/orders/'+path,{method:'POST',headers:{'content-type':'application/json','x-order-csrf':cfg.csrf},body:JSON.stringify(body||{})});
 const text=await r.text();let data;try{data=JSON.parse(text)}catch(e){}
 if(!r.ok)throw Error(data?.detail||text||'Request failed');
 return data;
}
async function testTracking(button){
 const field=byId('tracking-order-id');
 const orderId=field.value.trim();
 const notice=byId('tracking-status');
 if(!/^[0-9]{10,30}$/.test(orderId)){notice.textContent='Enter a TikTok order ID.';return}
 button.disabled=true;
 notice.textContent='Checking Shopify and submitting tracking to TikTok…';
 try{
  await send('tracking/pilot',{order_id:orderId});
  notice.textContent='Tracking verified in TikTok. You can now enable automatic tracking.';
  await trackingStatus();
 }catch(e){notice.textContent=e.message}
 finally{button.disabled=false}
}
async function startTrackingBrowser(button){
 const notice=byId('tracking-browser-status');
 button.disabled=true;
 notice.textContent='Starting the tracking browser…';
 try{
  await send('tracking/browser/start');
  notice.textContent='Tracking browser started. Sign in below if prompted.';
 }catch(e){notice.textContent=e.message}
 finally{button.disabled=false}
}
async function saveTracking(checkbox){
 const enabled=checkbox.checked;
 const notice=byId('tracking-status');
 checkbox.disabled=true;checkbox.dataset.saving='true';
 try{
  await send('tracking/settings',{enabled});
  notice.textContent=enabled?'Automatic tracking enabled. Leave automatic order checks on.':'Automatic tracking switched off.';
 }catch(e){checkbox.checked=!enabled;notice.textContent=e.message}
 finally{delete checkbox.dataset.saving;await trackingStatus()}
}

async function trackingStatus(){
 const field=byId('tracking-enabled');
 const status=byId('tracking-check');
 try{
  const response=await fetch(cfg.base+'/orders/tracking/status',{cache:'no-store'});
  if(!response.ok)throw Error();
  const data=await response.json();
  if(field.dataset.saving!=='true'){
   field.checked=data.enabled;
   field.disabled=!data.verified;
  }
  const last=data.checked_at?' Last check: '+new Date(data.checked_at).toLocaleTimeString('en-GB',{timeZone:'Europe/London'})+'.':'';
  status.textContent=(data.enabled?'Automatic tracking on. ':'Automatic tracking off. ')+data.message+last;
 }catch(e){status.textContent='Could not read tracking status. Reload Shop Sync.'}
}
trackingStatus();setInterval(trackingStatus,5000);
