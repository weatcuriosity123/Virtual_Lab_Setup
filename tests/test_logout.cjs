const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
for (const page of ['index.html', 'admin.html']) {
  const html = fs.readFileSync('backend/frontend/' + page, 'utf8');
  const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(s=>s.includes('function leave()'));
  for (const mode of ['cancel', 'click', 'broadcast', 'storage']) {
    const removed = [], redirects = [];
    let click, storage, channel, iframeRemoved = false;
    const context = {
      sessionStorage: { removeItem: key => removed.push(key) },
      localStorage: { setItem() {} },
      BroadcastChannel: class { constructor() { channel = this; } postMessage() {} },
      document: {
        querySelectorAll: selector => selector === 'iframe' ? [{remove(){iframeRemoved=true;}}] : [{addEventListener(_,fn){click=fn;}}],
        body: {replaceChildren(){},append(){}}, createElement: () => ({})
      },
      window: {confirm:()=>mode!=='cancel',location:{replace:url=>redirects.push(url)},addEventListener:(_,fn)=>storage=fn}
    };
    vm.runInNewContext(script, context);
    if (mode === 'broadcast') channel.onmessage({data:'logout'});
    else if (mode === 'storage') storage({key:'linuxLabLogout',newValue:'1'});
    else click();
    if (mode === 'cancel') {assert.equal(removed.length,0);assert.equal(redirects.length,0);}
    else {
      assert.deepEqual(removed,['linuxLabSession','labPendingStart']);
      assert.deepEqual(redirects,['/cdn-cgi/access/logout']);
      assert.equal(iframeRemoved,true);
      assert.equal(context.window.labSigningOut,true);
      channel.onmessage({data:'logout'});
      assert.equal(redirects.length,1);
    }
  }
}
console.log('Logout confirmation, cleanup, redirect and cross-tab notification checks passed.');
