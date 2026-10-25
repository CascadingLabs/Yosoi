// One evidence protocol, two real providers. Node is only the test driver.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import readline from 'node:readline';
import crypto from 'node:crypto';
const binary=path.resolve(process.argv[2]??'target/debug/yosoi'),source=process.argv[3];
if(!source)throw Error('usage: node verify_two_surfaces.mjs <yosoi binary> <video.mp4> [output]');
const output=path.resolve(process.argv[4]??'.local/two-surfaces-verification');fs.mkdirSync(output,{recursive:true});
const input=path.join(output,'input-copy.mp4');fs.copyFileSync(source,input);
const archive=path.join(output,'archive');let requests=0;
const server=http.createServer((req,res)=>{requests++;res.setHeader('Content-Type','text/html; charset=utf-8');res.end(req.url.includes('version=0.1.0')?'<html><head><title>Yosoi v0.1.0</title></head><body><h1>Yosoi</h1><p>This page is unavailable in v0.1.0. Showing the overview.</p></body></html>':'<html><head><title>What is Yosoi?</title></head><body><h1>What is Yosoi?</h1><details><summary aria-label="Documentation release">Latest</summary><a href="/archive?version=0.1.0">v0.1.0</a></details></body></html>');});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const url=`http://127.0.0.1:${server.address().port}/docs`;
const transcripts={web:[],video:[]};
async function open(kind,args){
 const child=spawn(binary,['surface',...args],{stdio:['pipe','pipe','pipe']});const exited=new Promise(resolve=>child.once('close',resolve));let stderr='';child.stderr.on('data',part=>stderr+=part);
 const iterator=readline.createInterface({input:child.stdout})[Symbol.asyncIterator]();let sequence=0;
 async function next(){const line=await iterator.next();assert.equal(line.done,false,stderr);assert.ok(Buffer.byteLength(line.value)<=4096,'reply budget exceeded');const value=JSON.parse(line.value);transcripts[kind].push(value);return value;}
 const ready=(await next()).result;assert.equal(ready.event,'ready');
 return {ready,async send(command,ok=true){const id=String(++sequence);child.stdin.write(JSON.stringify({id,...command})+'\n');const result=await next();assert.equal(result.id,id);assert.equal(result.ok,ok,JSON.stringify(result));return result.result??result;},async close(){if(child.exitCode===null){child.stdin.write(JSON.stringify({op:'close'})+'\n');await next();child.stdin.end();}assert.equal(await exited,0,stderr);},async abort(){child.stdin.end();if(child.exitCode===null){child.kill('SIGTERM');await exited;}}};
}
async function read(client,operation,continuation){return client.send({op:'read',request:{operation,budget:{bytes:3072,items:20},continuation:continuation??null}});}
async function find(client,query,tag){const page=(await read(client,{kind:'search',query})).data;for(const entry of page.entries){let reference=entry.reference;for(let depth=0;reference&&depth<8;depth++){let detail=(await read(client,{kind:'inspect',reference})).data;let text=detail.content;while(detail.next){detail=(await read(client,{kind:'inspect',reference},detail.next)).data;text+=detail.content;}if(JSON.parse(text).tag_name===tag)return reference;reference=(await read(client,{kind:'parent',reference})).data;}}throw Error('target missing');}
async function command(args,environment={}){const child=spawn(binary,args,{env:{...process.env,...environment},stdio:['ignore','pipe','pipe']});let out='',err='';child.stdout.on('data',v=>out+=v);child.stderr.on('data',v=>err+=v);const code=await new Promise(resolve=>child.once('close',resolve));assert.equal(code,0,err+out);return JSON.parse(out);}
let web,video;
try{
 web=await open('web',['web','--url',url,'--headless','--archive',archive,'--output',path.join(output,'web')]);
 const wd=await web.send({op:'describe'});assert.equal(wd.descriptor.controllable,true);assert.ok(wd.descriptor.capabilities.some(c=>c.access==='control'));
 const webReference=wd.root;assert.equal((await read(web,{kind:'overview'})).kind,'page');
 await web.send({op:'seek',position_us:0},false);await web.send({op:'attach'});await web.send({op:'hot'});
 const menu=await find(web,'Documentation release','summary');
 let focused=await web.send({op:'focus_evidence',reference:menu});
 let clicked=await web.send({op:'click',reference:focused.cursor.position.focus,target:{query:'Documentation release',tag:'summary'},expect:{kind:'text',text:'v0.1.0',present:true}});assert.equal(clicked.receipt.status,'Confirmed');
 const version=await find(web,'v0.1.0','a');focused=await web.send({op:'focus_evidence',reference:version});
 clicked=await web.send({op:'click',reference:focused.cursor.position.focus,target:{query:'v0.1.0',tag:'a'},expect:{kind:'navigation'}});assert.equal(clicked.receipt.status,'Confirmed');await web.close();web=null;
 video=await open('video',['video','--file',input,'--archive',archive,'--output',path.join(output,'video')]);
 const vd=await video.send({op:'describe'});assert.equal(vd.descriptor.controllable,false);assert.ok(vd.descriptor.capabilities.every(c=>c.access==='read'&&c.control_domain===null));
 const overview=await read(video,{kind:'overview'});assert.equal(overview.kind,'page');assert.equal(overview.data.coverage.complete,false);assert.ok(overview.data.entries.length>0);
 const part=overview.data.entries[0].reference;const expanded=await read(video,{kind:'expand',reference:part});assert.ok(expanded.data.entries.length>0);
 await video.send({op:'hot'},false);await video.send({op:'click',reference:{capture:'not-a-web-observation',node:0}},false);
 await read(video,{kind:'inspect',reference:webReference}).then(()=>{throw Error('cross-surface reference accepted')},error=>assert.ok(error));
 await video.send({op:'read',request:{operation:{kind:'search',query:'v0.1.0'}}},false);
 await video.send({op:'attach'});
 const position=(await video.send({op:'seek',position_us:3_500_000})).focus;
 const frame=await video.send({op:'frame',reference:position});assert.equal(frame.frame.reference.observation,vd.observation.id);assert.ok(frame.frame.position_us>=3_500_000);assert.ok(frame.frame.width>0&&frame.frame.width<=1920);assert.ok(frame.frame.height>0&&frame.frame.height<=1920);assert.ok(frame.frame.width<=video.ready.state.metadata.width);assert.ok(frame.frame.height<=video.ready.state.metadata.height);
 assert.equal(crypto.createHash('sha256').update(fs.readFileSync(frame.artifact.path)).digest('hex'),frame.frame.png_sha256);
 const crop=await video.send({op:'crop',reference:position,rect:{x:Math.max(0,frame.frame.width-340),y:Math.min(50,frame.frame.height-1),width:Math.min(320,frame.frame.width),height:Math.min(300,Math.max(1,frame.frame.height-50))}});assert.equal(crop.frame.width,320);assert.equal(crop.frame.height,300);assert.equal(crop.frame.canvas_width,frame.frame.width);
 const last=(await video.send({op:'seek',position_us:5_500_000})).focus;await video.send({op:'frame',reference:last});
 await video.send({op:'seek',position_us:999_999_999},false);await video.close();video=null;
 fs.unlinkSync(input);const networkBefore=requests;
 const replay=await command(['surface','replay','--record',path.join(output,'video/record.json'),'--repeat','3','--output',path.join(output,'replayed-pixels')],{CHROME:'/no-browser',CHROMEDRIVER:'/no-driver',YOSOI_FFMPEG:'/no-ffmpeg',YOSOI_FFPROBE:'/no-ffprobe'});
 assert.equal(replay.decoder_started,false);assert.equal(replay.browser_started,false);assert.equal(replay.controllable,false);assert.equal(replay.frames_verified,3);assert.equal(replay.iterations,3);assert.equal(requests,networkBefore);assert.ok(replay.frames.every(f=>fs.statSync(f.path).size>0));
 const webReplay=await command(['surface','replay','--record',path.join(output,'web/record.json'),'--query','This page is unavailable'],{CHROME:'/no-browser',CHROMEDRIVER:'/no-driver'});assert.equal(webReplay.actions.length,2);
 fs.writeFileSync(path.join(output,'transcripts.json'),JSON.stringify(transcripts,null,2));fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify({passed:true,web_controllable:true,video_controllable:false,web_replies:transcripts.web.length,video_replies:transcripts.video.length,offline:replay},null,2));console.log(JSON.stringify({passed:true,output,web_replies:transcripts.web.length,video_replies:transcripts.video.length}));
}finally{if(web)await web.abort();if(video)await video.abort();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
