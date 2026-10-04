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

test('SDK discovery reserves names and excludes internal yosoi', () => {
	const pkg = (name, sdk) => ({ id: name, name, metadata: { yosoi: { sdk } }, version: '0.1.0', manifest_path: '/repo/Cargo.toml', targets: [{ name: name.replaceAll('-', '_'), kind: ['lib'] }] });
	const metadata = { workspace_members: ['yosoi', 'yosoi-sdk'], packages: [pkg('yosoi', false), pkg('yosoi-sdk', true)] };
	assert.deepEqual(discoverSdks(metadata).map((s) => s.name), ['yosoi-sdk']);
	assert.throws(() => discoverSdks({ ...metadata, packages: [pkg('yosoi-sdk', false)] }), /reserved SDK/);
	assert.throws(() => discoverSdks({ workspace_members: ['yosoi'], packages: [pkg('yosoi', true)] }), /naming policy/);
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
