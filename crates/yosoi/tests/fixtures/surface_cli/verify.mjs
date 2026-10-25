// Exercise the public JSON-lines CLI through a real browser, one session at a time.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import readline from 'node:readline';
const executable=process.argv[2];
if(!executable)throw Error('usage: node verify.mjs <yosoi executable> [evidence directory]');
const output=path.resolve(process.argv[3]??'.local/surface-cli-verification');
fs.mkdirSync(output,{recursive:true});
const paragraph='This visible article paragraph is long enough to prove that the document has loaded with useful readable content. It is deterministic fixture evidence for the surface driver, and it has no remote services. ';
const server=http.createServer((req,res)=>{
 res.setHeader('content-type','text/html; charset=utf-8');
 if(req.url.startsWith('/article')){
  res.end(`<html><head><title>Surface article</title></head><body><article><h1>Surface reference article</h1>${`<p>${paragraph}</p>`.repeat(4)}</article>${req.url.includes('gated')?'<div style="position:fixed;inset:0;background:white"><h2>Keep reading with a <span>CNN subscription</span></h2></div>':''}</body></html>`);return;
 }
 res.end(`<html><head><title>Surface fixture</title></head><body><h1>News</h1><a href="/article" data-metadata="${'x'.repeat(4000)}">Surface reference article</a><form onsubmit="event.preventDefault();document.getElementById('result').textContent='Search complete'"><input placeholder="Search topic"><p id="result">Waiting</p></form><div style="position:relative;height:40px"><a href="/article">Covered link</a><div style="position:absolute;inset:0;background:white">Cover</div></div><div style="height:1500px"></div><div id="consent" style="position:fixed;inset:0;background:white"><h2>Legal Terms and Privacy</h2><button onclick="document.getElementById('consent').remove()">Agree</button></div></body></html>`);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const child=spawn(path.resolve(executable),['surface','drive','--headless','--url',origin,'--output',output],{stdio:['pipe','pipe','pipe']});
const exited=new Promise(resolve=>child.once('close',resolve));
let stderr='';child.stderr.on('data',part=>stderr+=part);
const lines=readline.createInterface({input:child.stdout});
const iterator=lines[Symbol.asyncIterator]();
const transcript=[];
let counter=0;
async function next(){
 const result=await iterator.next();assert.equal(result.done,false,stderr);
 assert.ok(Buffer.byteLength(result.value)<=4096,'wire response exceeds default budget');
 const value=JSON.parse(result.value);transcript.push(value);return value;
}
async function send(command,ok=true){
 const id=String(++counter);child.stdin.write(JSON.stringify({id,...command})+'\n');const reply=await next();assert.equal(reply.id,id);assert.ok(Buffer.byteLength(JSON.stringify(reply))<=(command.budget??4096));assert.equal(reply.ok,ok,JSON.stringify(reply));return reply.result??reply;
}
async function find(query,tag){
 const page=await send({op:'find',query});
 for(const entry of page.entries){
  let reference=entry.reference;
  for(let depth=0;reference&&depth<5;depth++){
   let detail=await send({op:'inspect',reference}),content=detail.content;
   if(detail.total_bytes>16000)break;
   while(detail.next){detail=await send({op:'inspect',reference,continuation:detail.next});content+=detail.content;}
   const record=JSON.parse(content);
   if(record.tag_name===tag)return reference;
   reference=await send({op:'parent',reference});
  }
 }
 throw Error(`target absent: ${query} / ${tag}`);
}
try {
 const ready=await next();assert.equal(ready.result.event,'ready');assert.equal(ready.result.state.cursor.live,false);
 let status=await send({op:'attach'});assert.equal(status.cursor.live,true);assert.equal(status.cursor.hot,false);
 const waited=await send({op:'wait',text:'Legal Terms and Privacy',present:true});assert.equal(waited.condition.state,'text_matched');
 const agree=await find('Agree','button');
 await send({op:'click',reference:agree},false); // Reader cannot act.
 await send({op:'hot'});
 const accepted=await send({op:'click',reference:agree,expect:{kind:'text',text:'Legal Terms and Privacy',present:false}});
 assert.equal(accepted.receipt.status,'Confirmed');assert.equal(accepted.observation.cursor.action_in_flight,false);
 await send({op:'click',reference:agree},false); // Exact old capture cannot be reused.
 let field=await find('Search topic','input');
 const filled=await send({op:'fill',reference:field,text:'Rust surfaces'});assert.equal(filled.receipt.status,'Confirmed');assert.equal(filled.outcome.value.matches,true);
 field=await find('Search topic','input');
 const key=await send({op:'key',reference:field,key:'Enter'});assert.equal(key.receipt.status,'Unconfirmed');
 assert.ok((await send({op:'find',query:'Search complete'})).entries.length>0);
 const covered=await find('Covered link','a');
 const blocked=await send({op:'click',reference:covered});assert.equal(blocked.receipt.status,'Rejected');assert.equal(blocked.receipt.dispatched,false);
 const article=await find('Surface reference article','a');
 const opened=await send({op:'click',reference:article,expect:{kind:'article'}});assert.equal(opened.receipt.status,'Confirmed');assert.equal(opened.observation.cursor.action_in_flight,false);assert.equal(opened.outcome.postcondition.readable,true);
 assert.ok((await send({op:'find',query:'Surface reference article',budget:1024})).entries.length>0);
 const screenshot=await send({op:'screenshot'});assert.ok(fs.statSync(screenshot.path).size>0);
 status=await send({op:'status'});
 const scrolled=await send({op:'scroll',reference:status.root,delta_y:200});assert.equal(scrolled.receipt.status,'Unconfirmed');
 status=await send({op:'status'});
 const navigation=await send({op:'navigate',reference:status.root,url:origin+'/article?gated'});assert.equal(navigation.receipt.status,'Confirmed');
 const gate=await send({op:'article'});assert.equal(gate.readable,false);assert.ok(gate.gate);
 await send({op:'missing_operation'},false);assert.ok(await send({op:'status'}));
 await send({op:'close'});child.stdin.end();
 const exit=await exited;assert.equal(exit,0,stderr);
 for(const mode of ['eof','sigterm']){
  const probe=spawn(path.resolve(executable),['surface','drive','--headless','--url',origin,'--output',path.join(output,mode)],{stdio:['pipe','pipe','pipe']});
  const ended=new Promise(resolve=>probe.once('close',(code,signal)=>resolve({code,signal})));
  const channel=readline.createInterface({input:probe.stdout})[Symbol.asyncIterator]();
  try{
   assert.equal(JSON.parse((await channel.next()).value).result.event,'ready');
   probe.stdin.write(JSON.stringify({id:'status',op:'status'})+'\n');
   assert.equal(JSON.parse((await channel.next()).value).id,'status');
   if(mode==='eof')probe.stdin.end();else probe.kill('SIGTERM');
   const stopped=await ended;assert.equal(stopped.code,0,JSON.stringify(stopped));
  }finally{probe.stdin.end();if(probe.exitCode===null){probe.kill('SIGTERM');await ended;}}
 }
 fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify({passed:true,replies:transcript.length,cases:['reader rejection','consent','stale reference','fill','key','covered target','article navigation','inspection continuation','1024-byte read','screenshot','scroll','navigate','subscription gate','invalid command recovery','wait','close','EOF cleanup','SIGTERM cleanup']},null,2));
 fs.writeFileSync(path.join(output,'transcript.json'),JSON.stringify(transcript,null,2));
 console.log(JSON.stringify({passed:true,replies:transcript.length,output}));
}finally{
 child.stdin.end();if(child.exitCode===null){child.kill('SIGTERM');await exited;}
 server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
}
