// An agent-style recording of the version menu, then offline and live replay.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import readline from 'node:readline';
const executable=path.resolve(process.argv[2]??'target/debug/yosoi');
const output=path.resolve(process.argv[3]??'.local/surface-recording-verification');
fs.mkdirSync(output,{recursive:true});
let requests=0;
const server=http.createServer((req,res)=>{
 requests++;res.setHeader('content-type','text/html; charset=utf-8');
 res.end(req.url.includes('version=0.1.0')?'<html><head><title>Yosoi v0.1.0</title></head><body><h1>Yosoi</h1><p>This page is unavailable in v0.1.0. Showing the overview.</p></body></html>':'<html><head><title>What is Yosoi?</title></head><body><h1>What is Yosoi?</h1><details><summary aria-label="Documentation release">Latest · 0.3.0</summary><a href="/archive?version=0.1.0">v0.1.0</a></details></body></html>');
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const url=`http://127.0.0.1:${server.address().port}/docs`;
const archive=path.join(output,'archive'),run=path.join(output,'recorded');
const child=spawn(executable,['surface','drive','--headless','--url',url,'--output',run,'--archive',archive],{stdio:['pipe','pipe','pipe']});
const exited=new Promise(resolve=>child.once('close',resolve));
const channel=readline.createInterface({input:child.stdout})[Symbol.asyncIterator]();
const transcript=[];let counter=0,stderr='';child.stderr.on('data',part=>stderr+=part);
async function next(){const line=await channel.next();assert.equal(line.done,false,stderr);assert.ok(Buffer.byteLength(line.value)<=4096);const value=JSON.parse(line.value);transcript.push(value);return value;}
async function send(command){const id=String(++counter);child.stdin.write(JSON.stringify({id,...command})+'\n');const reply=await next();assert.equal(reply.id,id);assert.equal(reply.ok,true,JSON.stringify(reply));return reply.result;}
async function find(query,tag){
 const found=await send({op:'find',query});
 for(const entry of found.entries){let reference=entry.reference;for(let depth=0;reference&&depth<8;depth++){
  let detail=await send({op:'inspect',reference}),content=detail.content;
  if(detail.total_bytes>16000)break;
  while(detail.next){detail=await send({op:'inspect',reference,continuation:detail.next});content+=detail.content;}
  if(JSON.parse(content).tag_name===tag)return reference;
  reference=await send({op:'parent',reference});
 }}throw Error('target absent');
}
async function command(args,environment={}){
 const process=spawn(executable,args,{env:{...globalThis.process.env,...environment},stdio:['ignore','pipe','pipe']});let stdout='',stderr='';process.stdout.on('data',part=>stdout+=part);process.stderr.on('data',part=>stderr+=part);
 const code=await new Promise(resolve=>process.once('close',resolve));assert.equal(code,0,stderr+stdout);return stdout.trim().split('\n').filter(Boolean).map(line=>JSON.parse(line));
}
try{
 const ready=await next();assert.equal(ready.result.state.recording.mode,'archive');
 await send({op:'attach'});await send({op:'hot'});
 const menu=await find('Documentation release','summary');
 const opened=await send({op:'click',reference:menu,target:{query:'Documentation release',tag:'summary'},expect:{kind:'text',text:'v0.1.0',present:true}});assert.equal(opened.receipt.status,'Confirmed');
 const old=await command(['surface','repeat','--record',path.join(run,'record.json'),'--count','1','--headless','--output',path.join(output,'unsealed')]).catch(error=>error);
 assert.ok(old instanceof Error,'unsealed live repetition must be rejected');assert.match(old.message,/not sealed/);
 const version=await find('v0.1.0','a');
 const selected=await send({op:'click',reference:version,target:{query:'v0.1.0',tag:'a'},expect:{kind:'navigation'}});assert.equal(selected.receipt.status,'Confirmed');
 await send({op:'close'});child.stdin.end();assert.equal(await exited,0,stderr);
 const handle=path.join(run,'record.json');assert.ok(fs.statSync(handle).size>0);
 const originalHandle=fs.readFileSync(handle,'utf8');assert.equal(JSON.parse(originalHandle).record.version,1);
 const networkBefore=requests;
 const offline=await command(['surface','replay','--record',handle,'--repeat','3','--query','This page is unavailable'],{CHROME:'/nonexistent-no-browser',CHROMEDRIVER:'/nonexistent-no-driver'});
 assert.equal(requests,networkBefore);assert.equal(offline[0].browser_started,false);assert.equal(offline[0].captures,3);assert.equal(offline[0].iterations,3);assert.ok(offline[0].matches.entries.length>0);
 const repeated=await command(['surface','repeat','--record',handle,'--count','3','--headless','--output',path.join(output,'repeat')]);
 assert.equal(fs.readFileSync(handle,'utf8'),originalHandle,'repeating must preserve the original immutable handle');
 assert.equal(repeated.length,3);assert.ok(repeated.every(row=>row.confirmed_clicks===2&&row.fresh_session));
 const restored=[];for(const row of repeated){const result=(await command(['surface','replay','--record',row.record]))[0];assert.equal(result.actions.length,2);restored.push(result.last_capture);}
 assert.equal(new Set([...restored,offline[0].last_capture]).size,4,'fresh browser sessions must issue different references');
 const badPath=path.join(output,'not-a-directory');fs.writeFileSync(badPath,'fixture');
 const refused=await command(['surface','drive','--url',url,'--archive',badPath,'--output',path.join(output,'bad-archive')],{CHROME:'/nonexistent-no-browser',CHROMEDRIVER:'/nonexistent-no-driver'}).catch(error=>error);
 assert.ok(refused instanceof Error);assert.match(refused.message,/not-a-directory/);assert.doesNotMatch(refused.message,/spawn.*nonexistent/);
 fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify({passed:true,replies:transcript.length,offline:offline[0],live_iterations:3,normal_automation_record:true,fresh_capture_identities:4,invalid_archive_rejected_before_browser:true,original_handle_unchanged:true},null,2));
 fs.writeFileSync(path.join(output,'transcript.json'),JSON.stringify(transcript,null,2));console.log(JSON.stringify({passed:true,output,offline_replays:3,live_iterations:3}));
}finally{child.stdin.end();if(child.exitCode===null){child.kill('SIGTERM');await exited;}server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
