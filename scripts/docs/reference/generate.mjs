#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import os from 'node:os';
import { buildReference, canonicalJson, sha256, sourceLink } from './model.mjs';
import { discoverSdks } from './sdk-discovery.mjs';

const scriptRoot = path.dirname(fileURLToPath(import.meta.url));
export const toolchain = JSON.parse(fs.readFileSync(path.join(scriptRoot, 'toolchain.json'), 'utf8'));
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const run = (program, args, cwd, env = {}) => execFileSync(program, args, { cwd, env: { ...process.env, CARGO_BUILD_JOBS: '1', RAYON_NUM_THREADS: '1', ...env }, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
const write = (file, value) => { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, canonicalJson(value)); };

function safeRelative(file) {
	if (!file || path.isAbsolute(file) || /[\\%?#\x00-\x1f]/.test(file) || file.split('/').some((part) => !part || part === '..' || part === '.')) throw new Error('Unsafe artifact path');
	return file;
}

function packageSpan(sdk, checkout) {
	const file = path.relative(checkout, sdk.manifestPath).split(path.sep).join('/');
	const lines = fs.readFileSync(sdk.manifestPath, 'utf8').split('\n');
	let inPackage = false, line = null;
	for (let index = 0; index < lines.length; index++) {
		if (/^\[/.test(lines[index])) inPackage = lines[index].trim() === '[package]';
		if (inPackage && /^version\s*=/.test(lines[index])) { line = index + 1; break; }
	}
	return line ? { filename: file, begin: [line, 1], end: [line, 1] } : { filename: file, begin: [1, 1], end: [lines.length, 1] };
}

export function localizePage(page, locale, overlay) {
	const entry = overlay?.items?.[page.id];
	if (entry && entry.docsDigest !== page.docsDigest) throw new Error(`Stale translation for ${page.id}`);
	if (entry?.docs && /```|~~~/.test(entry.docs)) throw new Error('Locale overlays must not replace executable example blocks');
	const localized = structuredClone(page);
	localized.locale = locale !== 'en' && !entry ? 'en' : locale;
	localized.requestedLocale = locale;
	localized.fallbackLocale = locale !== 'en' && !entry ? 'en' : null;
	if (entry) {
		localized.docs = entry.docs;
		localized.translation = { revision: overlay.revision, originalDigest: page.docsDigest, demo: overlay.demo === true };
	}
	localized.originalDocsDigest = page.docsDigest;
	localized.docsDigest = sha256(localized.docs);
	return localized;
}

export function writeReference({ pages, context, sdk, compiler, formatVersion, output, locales = ['en'], overlays = {}, preview = false }) {
	if (!/^[A-Za-z0-9][A-Za-z0-9._+-]*$/.test(context.version) || !locales.includes('en') || !locales.every((locale) => /^[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*$/.test(locale))) throw new Error('Invalid version or locales');
	const root = path.resolve(output);
	if (fs.existsSync(path.join(root, 'manifest.json'))) throw new Error('Reference output already exists; releases are immutable (choose a new output directory)');
	const descriptors = {};
	for (const slug of Object.keys(pages).sort(compare)) {
		safeRelative(slug);
		const hashes = {};
		for (const locale of locales) {
			const page = localizePage(pages[slug], locale, overlays[locale]);
			const bytes = canonicalJson(page);
			const file = path.join(root, locale, 'pages', `${slug}.json`);
			fs.mkdirSync(path.dirname(file), { recursive: true });
			fs.writeFileSync(file, bytes);
			hashes[locale] = sha256(bytes);
		}
		descriptors[slug] = { file: `pages/${slug}.json`, title: pages[slug].title, publicPath: pages[slug].publicPath, kind: pages[slug].kind, aliases: pages[slug].aliases || [], sha256: hashes.en, localeHashes: hashes };
	}
	const manifest = {
		schemaVersion: 1, kind: 'rust-api-reference', version: context.version,
		source: { repository: context.repository, commit: context.commit },
		sdk: { crate: sdk.crate, package: sdk.name, version: sdk.version, manifest: sourceLink(packageSpan(sdk, context.checkout), context) },
		build: { rustdocVersion: compiler.rustdocVersion, compilerCommit: compiler.compilerCommit, toolchain: toolchain.channel, formatVersion, target: context.target, features: context.features, generatorDigest: generatorDigest() },
		locales, pages: descriptors,
		preview,
	};
	const provenance = {
		schemaVersion: 1, type: 'rust-reference-build-metadata', status: preview ? 'unsigned-preview' : 'pending-attestation',
		sourceCommit: context.commit, repository: context.repository,
		contentDigest: sha256(canonicalJson(manifest)),
		generatorDigest: manifest.build.generatorDigest,
		toolchain: manifest.build,
		translations: Object.fromEntries(Object.entries(overlays).map(([locale, overlay]) => [locale, { revision: overlay.revision, digest: sha256(canonicalJson(overlay)), demo: overlay.demo === true }])),
	};
	write(path.join(root, 'provenance.json'), provenance);
	manifest.provenance = { status: provenance.status, file: 'provenance.json', sha256: sha256(canonicalJson(provenance)) };
	write(path.join(root, 'manifest.json'), manifest);
	return manifest;
}

export function generatorDigest() {
	return sha256(['model.mjs', 'generate.mjs', 'sdk-discovery.mjs', 'sdk-policy.json', 'toolchain.json'].map((file) => `${file}\n${fs.readFileSync(path.join(scriptRoot, file), 'utf8')}`).join('\n'));
}

export function verifyReference(directory) {
	const root = path.resolve(directory);
	const inspect = (dir) => { for (const entry of fs.readdirSync(dir, { withFileTypes: true })) { if (entry.isSymbolicLink()) throw new Error('Reference artifacts must not contain symlinks'); if (entry.isDirectory()) inspect(path.join(dir, entry.name)); } };
	inspect(root);
	const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
	if (manifest.schemaVersion !== 1 || manifest.kind !== 'rust-api-reference' || !/^[a-f0-9]{40}$/.test(manifest.source?.commit)) throw new Error('Invalid reference manifest');
	for (const locale of manifest.locales) for (const [slug, descriptor] of Object.entries(manifest.pages)) {
		safeRelative(slug); safeRelative(descriptor.file); safeRelative(locale);
		const bytes = fs.readFileSync(path.join(root, locale, descriptor.file));
		if (sha256(bytes) !== descriptor.localeHashes[locale]) throw new Error(`Reference integrity failed for ${locale}/${slug}`);
		const page = JSON.parse(bytes);
		for (const source of [page.source, page.reexportSource, ...(page.members || []).map((member) => member.source), ...(page.examples || []).map(example => example.source), ...(page.members || []).flatMap(member => (member.examples || []).map(example => example.source)), manifest.sdk.manifest]) {
			if (!source) continue;
			const expected = sourceLink({ filename: source.file, begin: [source.lineStart, 1], end: [source.lineEnd, 1] }, { ...manifest.source, checkout: root });
			if (!expected || expected.url !== source.url) throw new Error('Source link does not match the artifact commit');
		}
	}
	const provenanceBytes = fs.readFileSync(path.join(root, safeRelative(manifest.provenance.file)));
	if (sha256(provenanceBytes) !== manifest.provenance.sha256) throw new Error('Provenance metadata integrity failed');
	const base = { ...manifest }; delete base.provenance;
	const provenance = JSON.parse(provenanceBytes);
	if (provenance.sourceCommit !== manifest.source.commit || provenance.contentDigest !== sha256(canonicalJson(base))) throw new Error('Provenance content binding failed');
	return manifest;
}

export function packReference(directory, output) {
	verifyReference(directory);
	run('tar', ['--sort=name', '--mtime=@0', '--owner=0', '--group=0', '--numeric-owner', '--mode=u+rwX,go+rX,go-w', '-cf', path.resolve(output), '-C', path.resolve(directory), '.'], process.cwd());
	return sha256(fs.readFileSync(output));
}

export function assertArchiveBinding(directory, archive) {
	const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'rust-reference-binding-'));
	try {
		const expected = packReference(directory, path.join(temporary, 'expected.tar'));
		if (expected !== sha256(fs.readFileSync(archive))) throw new Error('Signed archive does not match the verified reference directory');
	} finally { fs.rmSync(temporary, { recursive: true, force: true }); }
}

function compilerInfo(channel, cwd) {
	const text = run('rustc', [`+${channel}`, '--version', '--verbose'], cwd);
	const compilerCommit = /^commit-hash: (\w+)$/m.exec(text)?.[1];
	if (compilerCommit !== toolchain.compilerCommit) throw new Error(`Rustdoc compiler mismatch. Install ${toolchain.channel}; expected ${toolchain.compilerCommit}, got ${compilerCommit}`);
	return { compilerCommit, rustdocVersion: run('rustdoc', [`+${channel}`, '--version'], cwd).trim() };
}

export function generateReference(options) {
	const repoRoot = path.resolve(options.repo || process.cwd());
	const commit = run('git', ['rev-parse', '--verify', '--end-of-options', `${options.source}^{commit}`], repoRoot).trim();
	if (!/^[a-f0-9]{40}$/.test(commit)) throw new Error('Source is not a full Git commit');
	const work = path.resolve(options.work || path.join(repoRoot, '.generated/rust-reference'));
	const checkout = path.join(work, 'checkouts', commit);
	fs.rmSync(checkout, { recursive: true, force: true });
	fs.mkdirSync(checkout, { recursive: true });
	if (!fs.existsSync(path.join(checkout, 'Cargo.toml'))) {
		const archive = path.join(work, `${commit}.tar`);
		run('git', ['archive', '--format=tar', `--output=${archive}`, commit], repoRoot);
		run('tar', ['-xf', archive, '-C', checkout], repoRoot);
		fs.unlinkSync(archive);
	}
	const channel = options.toolchain || toolchain.channel;
	const compiler = compilerInfo(channel, checkout);
	const metadataArgs = [`+${channel}`, 'metadata', '--locked', '--no-deps', '--format-version', '1'];
	if (options.offline) metadataArgs.push('--offline');
	const metadata = JSON.parse(run('cargo', metadataArgs, checkout));
	const sdks = discoverSdks(metadata);
	const sdk = options.sdk ? sdks.find((item) => item.name === options.sdk) : sdks.length === 1 ? sdks[0] : null;
	if (!sdk) throw new Error(`Choose a declared SDK with --sdk; found ${sdks.map((item) => item.name).join(', ')}`);
	const features = options.features ? options.features.split(',').filter(Boolean).sort(compare) : [];
	const target = options.target || toolchain.target;
	const targetDir = path.join(work, 'target');
	const jsonDir = options['from-json'] ? path.resolve(options['from-json']) : path.join(targetDir, target, 'doc');
	if (options['from-json'] && !options.preview) throw new Error('Imported rustdoc JSON is preview-only; release generation must extract the selected snapshot');
	const libraries = new Map(metadata.packages.flatMap((pkg) => pkg.targets.filter((t) => t.kind.some((kind) => ['lib', 'proc-macro', 'rlib'].includes(kind))).map((t) => [t.name, pkg.name])));
	const documents = new Map();
	const pending = [sdk.crate];
	while (pending.length) {
		const crate = pending.shift();
		if (documents.has(crate)) continue;
		const packageName = libraries.get(crate);
		if (!packageName) continue; // Third-party re-exports retain a labelled declaration link.
		if (!options['from-json']) {
			const args = [`+${channel}`, packageName === sdk.name ? 'rustdoc' : 'doc', '--locked', '-p', packageName, '--lib', '-j', '1', '--target', target];
			if (options.offline) args.push('--offline');
			if (packageName === sdk.name) {
				if (features.length) args.push('--features', features.join(','));
				args.push('--', '-Z', 'unstable-options', '--output-format', 'json');
				run('cargo', args, checkout, { CARGO_TARGET_DIR: targetDir });
			} else {
				// Document definitions under the same SDK feature graph. Selecting a
				// dependency alone would lose forwarded features and invent defaults.
				args.push('--no-deps', '--no-default-features', '-p', sdk.name);
				const sdkPackage = metadata.packages.find(pkg => pkg.name === sdk.name);
				const profile = [...(Object.hasOwn(sdkPackage.features, 'default') ? [`${sdk.name}/default`] : []), ...features.map(feature => `${sdk.name}/${feature}`)];
				if (profile.length) args.push('--features', profile.join(','));
				run('cargo', args, checkout, { CARGO_TARGET_DIR: targetDir, RUSTDOCFLAGS: '-Z unstable-options --output-format json' });
			}
		}
		let file = path.join(jsonDir, `${crate}.json`);
		// Proc macros run on the host even when the SDK target is explicit.
		const hostFile = path.join(targetDir, 'doc', `${crate}.json`);
		if (!options['from-json'] && !fs.existsSync(file) && fs.existsSync(hostFile)) file = hostFile;
		if (!fs.existsSync(file)) throw new Error(`Missing compiler JSON for in-repo crate ${crate}`);
		const doc = JSON.parse(fs.readFileSync(file, 'utf8'));
		documents.set(crate, doc);
		for (const external of Object.values(doc.external_crates)) if (libraries.has(external.name) && !documents.has(external.name)) pending.push(external.name);
	}
	const context = { crate: sdk.crate, repository: options.repository, commit, checkout, version: options.version || `${sdk.version}-preview`, target, features, readSource: (file) => fs.readFileSync(path.join(checkout, safeRelative(file)), 'utf8') };
	const pages = buildReference([...documents.values()], context);
	const overlays = options.overlays ? JSON.parse(fs.readFileSync(options.overlays, 'utf8')) : {};
	return writeReference({ pages, context, sdk, compiler, formatVersion: toolchain.rustdocJsonFormat, output: options.out, locales: (options.locales || 'en').split(','), overlays, preview: !!options.preview });
}

export function writePreviewCatalog({ work, versions, latest }) {
 const root = path.resolve(work || '.generated/rust-reference');
 if (!versions.includes(latest)) throw new Error('Preview latest must be an included version');
 const catalog = { schemaVersion: 1, preview: true, latest, versions: {} };
 for (const version of versions) {
  safeRelative(version);
  if (version.includes('/')) throw new Error('Invalid preview version');
  const directory = path.join(root, 'versions', version);
  const manifest = verifyReference(directory);
  if (!manifest.preview || manifest.version !== version) throw new Error('Preview catalog accepts only matching preview artifacts');
  catalog.versions[version] = { sourceCommit: manifest.source.commit, manifest: {
   repository: manifest.source.repository, commit: manifest.source.commit,
   path: `rust-reference/${version}/manifest.json`, sha256: sha256(fs.readFileSync(path.join(directory, 'manifest.json'))),
  } };
 }
 write(path.join(root, 'catalog.json'), catalog);
 return catalog;
}

export const HELP = `Rust SDK reference tooling (Node orchestrator, one Cargo worker):
  node scripts/docs/reference/generate.mjs discover [--repo checkout] [--toolchain nightly]
  node scripts/docs/reference/generate.mjs generate --source <commit-or-tag> --repository <Owner/Repo> --out <new-directory> [--sdk yosoi-sdk] [--version label] [--locales en,fr] [--overlays file] [--toolchain nightly-2026-09-06] [--features browser] [--preview --from-json directory]
  node scripts/docs/reference/generate.mjs preview-catalog --versions v1,v2 --latest v2 [--work .generated/rust-reference]
  node scripts/docs/reference/generate.mjs verify --dir <artifact-directory>
  node scripts/docs/reference/generate.mjs pack --dir <artifact-directory> --out <bundle.tar>
  node scripts/docs/reference/generate.mjs verify-attestation --dir <artifact-directory> --archive <bundle.tar> --bundle <sigstore.json> --repository <Owner/Repo> --signer-workflow <Owner/Repo/.github/workflows/file.yml>
Generation checks out the exact commit; imported JSON is local-preview-only. verify checks integrity, not signed provenance. verify-attestation requires GitHub CLI and trusted workflow identity.`;

function options(argv) {
	const result = {};
	for (let i = 0; i < argv.length; i++) {
		if (!argv[i].startsWith('--')) throw new Error(`Unexpected argument ${argv[i]}`);
		const name = argv[i].slice(2);
		if (name === 'preview' || name === 'offline') result[name] = true;
		else { if (!argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error(`Missing ${name}`); result[name] = argv[++i]; }
	}
	return result;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	try {
		const [command, ...args] = process.argv.slice(2);
		if (!command || command === '--help') console.log(HELP);
		else {
			const o = options(args);
			if (command === 'generate') { const m = generateReference(o); console.log(`${m.sdk.package}: ${Object.keys(m.pages).length} pages, ${m.locales.join(', ')} at ${m.source.commit}`); }
			else if (command === 'discover') console.log(JSON.stringify(discoverSdks(JSON.parse(run('cargo', [`+${o.toolchain || toolchain.channel}`, 'metadata', '--locked', '--offline', '--no-deps', '--format-version', '1'], o.repo || process.cwd()))), null, 2));
			else if (command === 'preview-catalog') { const catalog = writePreviewCatalog({ work: o.work, versions: (o.versions || '').split(','), latest: o.latest }); console.log(`Preview catalog: ${Object.keys(catalog.versions).join(', ')}`); }
			else if (command === 'verify') { const m = verifyReference(o.dir); console.log(`Integrity verified: ${m.version}; provenance status: ${m.provenance.status}`); }
			else if (command === 'pack') {
				console.log(`sha256:${packReference(o.dir, o.out)}`);
			} else if (command === 'verify-attestation') {
				const manifest = verifyReference(o.dir);
				if (!o.bundle || !o.archive || !o.repository || !o['signer-workflow']) throw new Error('Require archive, attestation bundle, repository, and trusted signer workflow');
				assertArchiveBinding(o.dir, o.archive);
				console.log(run('gh', ['attestation', 'verify', path.resolve(o.archive), '--bundle', path.resolve(o.bundle), '--repo', o.repository, '--signer-workflow', o['signer-workflow'], '--source-digest', manifest.source.commit], process.cwd()));
			} else throw new Error(`Unknown command ${command}`);
		}
	} catch (error) { console.error(error.message); process.exitCode = 1; }
}
