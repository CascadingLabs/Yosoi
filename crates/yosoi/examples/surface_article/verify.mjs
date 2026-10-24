// Native browser regression cases for the Rust example; no model or index sidecar.
import http from 'node:http';
import {spawn} from 'node:child_process';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import path from 'node:path';
const executable = process.argv[2];
if (!executable) throw Error('usage: node verify.mjs <surface_article executable> [evidence directory]');
const outputRoot = path.resolve(process.argv[3] ?? '.local/index-article-verification');
fs.mkdirSync(outputRoot, {recursive: true});
const text='This is a deliberately long readable article paragraph for the observation index experiment. It provides enough real visible text to distinguish loaded content from a navigation shell or an advertisement. ';
const server=http.createServer((req,res)=>{
 res.setHeader('Content-Type','text/html; charset=utf-8');
 if(req.url.startsWith('/article')){
  const gated=req.url.includes('gated');
  res.end(`<html><head><title>Fixture article</title></head><body><article><h1>Index reference article</h1>${Array.from({length:4},()=>`<p>${text}</p>`).join('')}</article>${gated?'<div style="position:fixed;inset:0;background:#fffe"><h2>Keep reading with a <span>CNN subscription</span></h2></div>':''}</body></html>`);return;
 }
 const name=req.url.split('/').at(-1);
 const gate=name==='gated', blocked=name==='blocked', unchanged=name==='unchanged';
 res.end(`<html><head><title>Fixture home</title></head><body><main><h1>News</h1><div style="width:150px"><a href="/article${gate?'?gated':''}" data-metadata="${'x'.repeat(4000)}" ${unchanged?'onclick="event.preventDefault()"':''} style="font-size:24px">Index reference article</a></div></main>${name==='controls'?'<iframe srcdoc="ad&#127;payload"></iframe>':''}${blocked?'<div style="position:fixed;inset:0;background:white;z-index:1">Blocking overlay</div>':''}<div id="consent" style="position:fixed;inset:0;background:white;z-index:2"><h2>Legal Terms and Privacy</h2><button onclick="document.getElementById(\'consent\').remove()">Agree</button></div></body></html>`);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const url=`http://127.0.0.1:${server.address().port}`;
const results=[];
try {
 for(const name of ['free','gated','blocked','no-consent','controls','unchanged']){
  const output=path.join(outputRoot,name);
  const args=['--headless','--url',`${url}/${name}`,'--query','Index reference article','--output',output];
  if(name!=='no-consent')args.push('--accept-terms');
  const child=spawn(path.resolve(executable),args,{stdio:['ignore','pipe','pipe']});
  let log='';child.stdout.on('data',part=>log+=part);child.stderr.on('data',part=>log+=part);
  const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',resolve)});
  const t=JSON.parse(fs.readFileSync(`${output}/trace.json`));
  const events=t.events, receipts=events.filter(e=>e.operation==='action.receipt').map(e=>e.evidence);
  const reads=events.filter(e=>e.operation.startsWith('surface.'));
  assert.ok(reads.length>0);assert.ok(reads.every(e=>e.evidence.response_bytes<=4096));
  if(['free','controls'].includes(name)){assert.equal(code,0,log);assert.equal(t.outcome.state,'readable');assert.equal(receipts.at(-1).status,'Confirmed');}
  if(name==='gated'){assert.equal(t.outcome.state,'subscription_required');assert.equal(t.outcome.readable,false);assert.equal(receipts.at(-1).status,'Confirmed');}
  if(name==='blocked'){assert.equal(code,1);assert.equal(events.filter(e=>e.operation==='action.dispatch').length,1);assert.ok(events.some(e=>e.operation==='target.eligibility'&&e.evidence.native.topmost===false));}
  if(name==='no-consent'){assert.equal(t.outcome.state,'consent_required');assert.equal(events.filter(e=>e.operation==='action.dispatch').length,0);}
  if(name==='controls')assert.ok(events.some(e=>e.operation==='capture'&&e.evidence.normalized_strings.length>0));
  if(name==='unchanged'){assert.equal(t.outcome.state,'timeout');assert.equal(receipts.at(-1).status,'Unconfirmed');assert.match(receipts.at(-1).note,/not observed/);}
  const result={case:name,passed:true,state:t.outcome.state,receipts:receipts.map(r=>r.status),reads:reads.length,max_read_bytes:Math.max(...reads.map(e=>e.evidence.response_bytes))};results.push(result);console.log(JSON.stringify(result));
 }
 fs.writeFileSync(path.join(outputRoot,'verification.json'),JSON.stringify({passed:true,cases:results},null,2));
} finally {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
