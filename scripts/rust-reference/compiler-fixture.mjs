// Fast real-compiler integration; no Yosoi dependency build or provider calls.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { generateReference, verifyReference } from './generate.mjs';
const root=fs.mkdtempSync(path.join(os.tmpdir(),'sdk-rustdoc-fixture-'));
const run=(cmd,args)=>execFileSync(cmd,args,{cwd:root,encoding:'utf8',env:{...process.env,CARGO_BUILD_JOBS:'1',RAYON_NUM_THREADS:'1'}}).trim();
try {
 fs.mkdirSync(path.join(root,'src'));
 fs.writeFileSync(path.join(root,'Cargo.toml'),`[package]\nname="fixture-sdk"\nversion="0.1.0"\nedition="2021"\n[package.metadata.yosoi]\nsdk=true\n[features]\nextra=["fixture-core/extra"]\n[dependencies]\nfixture-core={path="core",default-features=false}\n[workspace]\nmembers=["core"]\n`);
 fs.mkdirSync(path.join(root,'core/src'),{recursive:true});
 fs.writeFileSync(path.join(root,'core/Cargo.toml'),'[package]\nname="fixture-core"\nversion="0.1.0"\nedition="2021"\n[features]\nextra=[]\n');
 fs.writeFileSync(path.join(root,'core/src/lib.rs'),'#[cfg(feature="extra")]\npub struct FeatureItem;\n');
 const source=`//! Compiler fixture.
/// A public SDK item.
/// \`\`\`rust
/// let item = fixture_sdk::Public;
/// \`\`\`
pub struct Public;
pub enum Payload { Tuple(u64), Record { value: bool } }
impl Public {
 /// A regular method.
 pub fn base(&self) -> usize { 1 }
 #[cfg(feature="extra")]
 pub fn extra(&self) -> bool { true }
}
#[doc(hidden)]
pub fn hidden() {}
fn private() {}
mod implementation {
 /// Re-exported SDK item.
 pub struct Exported;
}
pub use implementation::Exported as Alias;
macro_rules! make_item { () => { pub fn generated() {} } }
make_item!();
#[cfg(feature="extra")]
pub use fixture_core::FeatureItem;
`;
 fs.writeFileSync(path.join(root,'src/lib.rs'),source);
 run('git',['init','--quiet']);run('cargo',['+nightly','generate-lockfile','--offline']);
 const commit=()=>{run('git',['add','Cargo.toml','Cargo.lock','src','core']);run('git',['-c','user.name=Local Fixture','-c','user.email=fixture@example.invalid','commit','--quiet','-m','fixture']);return run('git',['rev-parse','HEAD']);};
 const first=commit();
 const options={repo:root,repository:'CascadingLabs/fixture',sdk:'fixture-sdk',toolchain:'nightly',offline:true,preview:true};
 const one=generateReference({...options,source:first,version:'0.1.0',out:path.join(root,'one')});
 const get=(manifest,dir,title)=>{const descriptor=Object.values(manifest.pages).find(p=>p.title===title);assert(descriptor,title);return JSON.parse(fs.readFileSync(path.join(root,dir,'en',descriptor.file)));};
 const payload=get(one,'one','fixture_sdk::Payload');
 assert(payload.members.some(member=>member.signature==='Tuple(u64)'));
 assert(payload.members.some(member=>member.signature==='Record { value: bool }'));
 const publicOne=get(one,'one','fixture_sdk::Public');
 assert(publicOne.members.some(m=>m.publicPath.endsWith('::base')));
 assert(!publicOne.members.some(m=>m.publicPath.endsWith('::extra')));
 assert(!Object.values(one.pages).some(p=>/::(?:hidden|private)$/.test(p.title)));
 assert(Object.values(one.pages).some(p=>p.title==='fixture_sdk::Alias'));
 assert(Object.values(one.pages).some(p=>p.title==='fixture_sdk::generated'));
 assert.equal(publicOne.examples[0].source.lineStart,3);
 fs.writeFileSync(path.join(root,'src/lib.rs'),'// New release adds lines and changes routes.\n\n'+source.replaceAll('Public','Renamed'));
 const second=commit();
 const two=generateReference({...options,source:second,version:'0.2.0',features:'extra',out:path.join(root,'two')});
 const publicTwo=get(two,'two','fixture_sdk::Renamed');
 assert(Object.values(two.pages).some(p=>p.title==='fixture_sdk::FeatureItem'));
 assert.equal(get(two,'two','fixture_sdk::FeatureItem').kind,'struct');
 assert(publicTwo.members.some(m=>m.publicPath.endsWith('::extra')));
 assert.equal(publicTwo.source.lineStart,publicOne.source.lineStart+2);
 assert(publicOne.source.url.includes(first));assert(publicTwo.source.url.includes(second));
 assert(!Object.values(two.pages).some(p=>p.title==='fixture_sdk::Public'));
 verifyReference(path.join(root,'one'));verifyReference(path.join(root,'two'));
 console.log('PASS actual Rustdoc: two commits/routes, features, public/private/hidden, alias, macro, exact example and definition spans');
} finally {fs.rmSync(root,{recursive:true,force:true});}
