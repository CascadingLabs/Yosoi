import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { buildReference, sourceLink, typeText, sha256, canonicalJson } from './model.mjs';
import { discoverSdks } from './sdk-discovery.mjs';
import { writeReference, verifyReference, localizePage, packReference, assertArchiveBinding } from './generate.mjs';

const identity = { repository: 'Owner/Repo', commit: 'a'.repeat(40) };
const span = { filename: 'src/lib.rs', begin: [12, 1], end: [14, 2] };
const item = (id, name, inner, visibility = 'public', attrs = []) => ({ id, name, inner, visibility, attrs, span, docs: 'Source documentation.' });
function fixture() {
	return { format_version: 61, root: 0, paths: {}, external_crates: {}, index: {
		0: item(0, 'demo_sdk', { module: { items: [1, 2, 3] } }),
		1: item(1, 'Entry', { struct: { kind: { plain: { fields: [] } }, generics: { params: [], where_predicates: [] }, impls: [4] } }),
		2: item(2, 'Private', { struct: { kind: { plain: { fields: [] } }, generics: { params: [], where_predicates: [] }, impls: [] } }, 'crate'),
		3: item(3, 'Hidden', { struct: { kind: { plain: { fields: [] } }, generics: { params: [], where_predicates: [] }, impls: [] } }, 'public', [{ other: '#[doc(hidden)]' }]),
		4: item(4, null, { impl: { trait: null, is_synthetic: false, blanket_impl: null, items: [5] } }, 'default'),
		5: item(5, 'value', { function: { sig: { inputs: [['self', { borrowed_ref: { type: { generic: 'Self' }, is_mutable: false, lifetime: null } }]], output: { primitive: 'u64' } }, header: {}, generics: { params: [], where_predicates: [] } } }),
	} };
}

test('SDK discovery reserves names and excludes development support', () => {
	const pkg = (name, sdk) => ({ id: name, name, metadata: { yosoi: { sdk } }, version: '0.1.0', manifest_path: '/repo/Cargo.toml', targets: [{ name: name.replaceAll('-', '_'), kind: ['lib'] }] });
	const metadata = { workspace_members: ['yosoi-dev-support', 'yosoi'], packages: [pkg('yosoi-dev-support', false), pkg('yosoi', true)] };
	assert.deepEqual(discoverSdks(metadata).map((s) => s.name), ['yosoi']);
	assert.throws(() => discoverSdks({ ...metadata, packages: [pkg('yosoi', false)] }), /reserved SDK/);
	assert.throws(() => discoverSdks({ workspace_members: ['yosoi-dev-support'], packages: [pkg('yosoi-dev-support', true)] }), /naming policy/);
});

test('compiler model publishes SDK reachability, public members, and exact definition spans', () => {
	const pages = buildReference([fixture()], { ...identity, checkout: '/repo', crate: 'demo_sdk' });
	assert.deepEqual(Object.keys(pages), ['demo-sdk/struct/entry', 'index']);
	assert.equal(pages['demo-sdk/struct/entry'].members[0].signature, 'pub fn value(&self) -> u64');
	assert.equal(pages['demo-sdk/struct/entry'].source.url, `https://github.com/Owner/Repo/blob/${identity.commit}/src/lib.rs#L12-L14`);
	assert.equal(Object.values(pages).some((p) => /Private|Hidden/.test(p.publicPath)), false);
	assert.throws(() => buildReference([{ ...fixture(), format_version: 60 }], { crate: 'demo_sdk' }), /Unsupported rustdoc/);
});

test('source paths cannot escape the snapshot or use moving tags', () => {
	assert.equal(sourceLink({ ...span, filename: '../private.rs' }, { ...identity, checkout: '/repo' }), null);
	assert.throws(() => sourceLink(span, { ...identity, commit: 'main', checkout: '/repo' }), /full commit hash/);
	assert.equal(typeText({ impl_trait: [{ trait_bound: { trait: { path: 'Into', args: { angle_bracketed: { args: [{ type: { resolved_path: { path: 'String', args: null } } }], constraints: [] } } }, modifier: 'none' } }] }), 'impl Into<String>');
});

test('signatures follow compiler type identities across private module moves', () => {
	const moved = fixture();
	moved.index[5].inner.function.sig.output = { resolved_path: { id: 1, path: 'crate::internal::engine::Entry', args: null } };
	const pages = buildReference([moved], { ...identity, checkout: '/repo', crate: 'demo_sdk' });
	assert.equal(pages['demo-sdk/struct/entry'].members[0].signature, 'pub fn value(&self) -> demo_sdk::Entry');
	// An unrelated type with the same name must retain its own identity.
	moved.index[5].inner.function.sig.output.resolved_path.id = 2;
	const changed = buildReference([moved], { ...identity, checkout: '/repo', crate: 'demo_sdk' });
	assert.notEqual(changed['demo-sdk/struct/entry'].members[0].signature, pages['demo-sdk/struct/entry'].members[0].signature);
});

test('third-party reexports retain the compiler public import rather than a private definition path', () => {
	const doc = fixture();
	doc.index[0].inner.module.items.push(6);
	doc.index[6] = item(6, 'External', { use: { name: 'External', id: 100, source: 'crate::internal::External', is_glob: false } });
	doc.index[7] = item(7, 'External', { use: { name: 'External', id: 100, source: 'upstream::External', is_glob: false } });
	doc.paths[100] = { path: ['upstream', 'private', 'External'], kind: 'struct' };
	const pages = buildReference([doc], { ...identity, checkout: '/repo', crate: 'demo_sdk' });
	assert.equal(pages['demo-sdk/reexport/external'].signature, 'pub use upstream::External;');
});

test('conversion methods belong to their receiver even when rustdoc lists them on the input', () => {
	const doc = fixture();
	doc.index[0].inner.module.items.push(6);
	doc.index[6] = item(6, 'Converted', { struct: { kind: { plain: { fields: [] } }, generics: { params: [], where_predicates: [] }, impls: [] } });
	doc.index[1].inner.struct.impls.push(7);
	doc.index[7] = item(7, null, { impl: { trait: { path: 'From' }, for: { resolved_path: { id: 6, path: 'Converted', args: null } }, is_synthetic: false, blanket_impl: null, items: [8] } }, 'default');
	doc.index[8] = item(8, 'from', { function: { sig: { inputs: [['source', { resolved_path: { id: 1, path: 'Entry', args: null } }]], output: { generic: 'Self' } }, header: {}, generics: { params: [], where_predicates: [] } } }, 'default');
	const pages = buildReference([doc], { ...identity, checkout: '/repo', crate: 'demo_sdk' });
	assert.equal(pages['demo-sdk/struct/entry'].members.some(member => member.trait === 'From'), false);
	assert.equal(pages['demo-sdk/struct/converted'].members[0].signature, 'fn from(source: demo_sdk::Entry) -> Self');
	assert.equal(pages['demo-sdk/struct/converted'].members[0].trait, 'From');
	doc.index[8].inner.function.sig.inputs[0][1].resolved_path = { id: 2, path: 'Private', args: null };
	const privateInput = buildReference([doc], { ...identity, checkout: '/repo', crate: 'demo_sdk' });
	assert.equal(privateInput['demo-sdk/struct/converted'].members[0].signature, 'fn from(source: Private) -> Self');
	assert.equal(Object.values(privateInput).some(page => /Private|Hidden/.test(page.publicPath)), false);
	doc.index[0].inner.module.items.push(9);
	doc.index[9] = item(9, 'internal', { module: { items: [10] } }, 'crate');
	doc.index[10] = item(10, 'PrivateTrait', { trait: { generics: { params: [], where_predicates: [] }, items: [] } });
	doc.index[11] = item(11, null, { impl: { trait: { id: 10, path: 'PrivateTrait' }, for: { resolved_path: { id: 6, path: 'Converted', args: null } }, is_synthetic: false, blanket_impl: null, items: [12] } }, 'default');
	doc.index[12] = { ...doc.index[8], id: 12, name: 'private_operation' };
	const privateTrait = buildReference([doc], { ...identity, checkout: '/repo', crate: 'demo_sdk' });
	assert.equal(privateTrait['demo-sdk/struct/converted'].members.some(member => member.trait === 'PrivateTrait'), false);
	assert.equal(Object.values(privateTrait).some(page => /::internal|PrivateTrait/.test(page.publicPath)), false);
});

test('locale overlays bind to original prose and do not alter signatures or examples', () => {
	const p = { id: 'struct:demo_sdk::Entry', docs: 'English.', docsDigest: sha256('English.'), signature: 'pub struct Entry', examples: [{ code: 'let n = 1;' }] };
	const overlay = { revision: '1', demo: true, items: { [p.id]: { docsDigest: p.docsDigest, docs: 'Français.' } } };
	const translated = localizePage(p, 'fr', overlay);
	assert.equal(translated.docs, 'Français.');
	assert.equal(translated.signature, p.signature);
	assert.deepEqual(translated.examples, p.examples);
	assert.equal(translated.originalDocsDigest, p.docsDigest);
	assert.equal(translated.docsDigest, sha256('Français.'));
	assert.equal(localizePage(p, 'fr').fallbackLocale, 'en');
	assert.throws(() => localizePage(p, 'fr', { ...overlay, items: { [p.id]: { docsDigest: '0'.repeat(64), docs: 'Stale.' } } }), /Stale translation/);
});

test('artifacts verify every locale and bind source and provenance without claiming attestation', (context) => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rust-reference-test-'));
	context.after(() => fs.rmSync(root, { recursive: true, force: true }));
	fs.writeFileSync(path.join(root, 'Cargo.toml'), '[package]\nname="demo-sdk"\nversion="0.1.0"\n');
	const pages = buildReference([fixture()], { ...identity, checkout: root, crate: 'demo_sdk' });
	const sdk = { crate: 'demo_sdk', name: 'demo-sdk', version: '0.1.0', manifestPath: path.join(root, 'Cargo.toml') };
	const output = path.join(root, 'artifact');
	const manifest = writeReference({ pages, context: { ...identity, checkout: root, version: '0.1.0-preview', target: 'test', features: [] }, sdk, compiler: { rustdocVersion: 'test', compilerCommit: 'b'.repeat(40) }, formatVersion: 61, output, locales: ['en', 'fr'], preview: true });
	assert.equal(verifyReference(output).source.commit, identity.commit);
	assert.equal(manifest.provenance.status, 'unsigned-preview');
	const tar = path.join(root, 'reference.tar');
	packReference(output, tar);
	assertArchiveBinding(output, tar);
	fs.appendFileSync(tar, 'changed archive');
	assert.throws(() => assertArchiveBinding(output, tar), /does not match/);
	fs.appendFileSync(path.join(output, 'fr/pages/index.json'), 'changed page');
	assert.throws(() => verifyReference(output), /integrity failed/);
});

test('Rust examples link to authored comment lines when an exact match exists', () => {
	const doc = fixture();
	doc.index[1].docs = 'Example:\n\n```rust\nlet n = 1;\n```';
	const lines = ['/// Example:', '///', '/// ```rust', '/// let n = 1;', '/// ```', 'pub struct Entry;'];
	doc.index[1].span = { filename: 'src/lib.rs', begin: [6, 1], end: [6, 18] };
	const pages = buildReference([doc], { ...identity, checkout: '/repo', crate: 'demo_sdk', readSource: () => lines.join('\n') });
	assert.equal(pages['demo-sdk/struct/entry'].examples[0].label, 'Example source lines');
	assert.equal(pages['demo-sdk/struct/entry'].examples[0].source.lineStart, 3);
	assert.equal(pages['demo-sdk/struct/entry'].examples[0].source.lineEnd, 5);
});
