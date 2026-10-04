import { createHash } from 'node:crypto';
import path from 'node:path';

export const FORMAT_VERSION = 61;
export const sha256 = (value) => createHash('sha256').update(value).digest('hex');
export const canonicalJson = (value) => `${JSON.stringify(value, null, 2)}\n`;
const hidden = (item) => JSON.stringify(item?.attrs || []).includes('doc(hidden)') || (item?.attrs || []).some((attribute) => Object.hasOwn(attribute, 'doc_hidden'));
const publicItem = (item) => item && item.visibility === 'public' && !hidden(item);
const kindOf = (item) => Object.keys(item.inner)[0];
const slugPart = (value) => value.replace(/^r#/, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

export function sourceLink(span, { repository, commit, checkout }) {
	if (!span) return null;
	if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*\/[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(repository) || !/^[a-f0-9]{40}$/.test(commit)) throw new Error('Source links require a repository and full commit hash');
	let file = span.filename.replaceAll('\\', '/');
	if (path.isAbsolute(file)) file = path.relative(checkout, file).split(path.sep).join('/');
	if (!file || file.startsWith('../') || file.startsWith('/') || file.split('/').some((part) => !part || part === '..' || part === '.') || /[%?#\x00-\x1f]/.test(file)) return null;
	const lineStart = span.begin?.[0];
	const lineEnd = span.end?.[0];
	if (!Number.isSafeInteger(lineStart) || !Number.isSafeInteger(lineEnd) || lineStart < 1 || lineEnd < lineStart) return null;
	return { file, lineStart, lineEnd, url: `https://github.com/${repository}/blob/${commit}/${file.split('/').map(encodeURIComponent).join('/')}#L${lineStart}-L${lineEnd}` };
}

function argsText(args) {
	if (!args) return '';
	if (args.parenthesized) return `(${args.parenthesized.inputs.map(typeText).join(', ')})${args.parenthesized.output ? ` -> ${typeText(args.parenthesized.output)}` : ''}`;
	const a = args.angle_bracketed;
	if (!a) return '';
	const pieces = a.args.map((arg) => arg.type ? typeText(arg.type) : arg.lifetime ?? arg.const?.expr ?? '_');
	for (const bound of a.constraints || []) pieces.push(`${bound.name}${argsText(bound.args)} ${bound.binding?.equality ? `= ${typeText(bound.binding.equality.type)}` : `: ${(bound.binding?.constraint || []).map(boundText).join(' + ')}`}`);
	return pieces.length ? `<${pieces.join(', ')}>` : '';
}

function boundText(bound) {
	if (bound.outlives) return bound.outlives;
	if (bound.trait_bound) return `${bound.trait_bound.modifier === 'maybe' ? '?' : ''}${bound.trait_bound.trait.path}${argsText(bound.trait_bound.trait.args)}`;
	return '_';
}

export function typeText(type) {
	if (type === null || type === undefined) return '()';
	if (type.primitive) return type.primitive;
	if (type.generic) return type.generic;
	if (type.resolved_path) return `${type.resolved_path.path}${argsText(type.resolved_path.args)}`;
	if (type.borrowed_ref) return `&${type.borrowed_ref.lifetime ? `${type.borrowed_ref.lifetime} ` : ''}${type.borrowed_ref.is_mutable ? 'mut ' : ''}${typeText(type.borrowed_ref.type)}`;
	if (type.raw_pointer) return `*${type.raw_pointer.is_mutable ? 'mut' : 'const'} ${typeText(type.raw_pointer.type)}`;
	if (type.slice) return `[${typeText(type.slice)}]`;
	if (type.array) return `[${typeText(type.array.type)}; ${type.array.len}]`;
	if (type.tuple) return `(${type.tuple.map(typeText).join(', ')}${type.tuple.length === 1 ? ',' : ''})`;
	if (type.impl_trait) return `impl ${type.impl_trait.map(boundText).join(' + ')}`;
	if (type.dyn_trait) return `dyn ${type.dyn_trait.traits.map((trait) => `${trait.trait.path}${argsText(trait.trait.args)}`).join(' + ')}${type.dyn_trait.lifetime ? ` + ${type.dyn_trait.lifetime}` : ''}`;
	if (type.qualified_path) { const q = type.qualified_path; return `<${typeText(q.self_type)}${q.trait ? ` as ${q.trait.path}${argsText(q.trait.args)}` : ''}>::${q.name}${argsText(q.args)}`; }
	if (type.function_pointer) return functionSignature('', type.function_pointer.sig, type.function_pointer.header, type.function_pointer.generic_params || []);
	if (type.infer !== undefined) return '_';
	if (type.pat) return typeText(type.pat.type);
	throw new Error(`Unsupported rustdoc type: ${Object.keys(type).join(', ')}`);
}

function genericText(params) {
	const p = params.filter((param) => !param.kind?.type?.is_synthetic).map((param) => {
		if (param.kind.lifetime) return `${param.name}${param.kind.lifetime.outlives.length ? `: ${param.kind.lifetime.outlives.join(' + ')}` : ''}`;
		if (param.kind.const) return `const ${param.name}: ${typeText(param.kind.const.type)}${param.kind.const.default ? ` = ${param.kind.const.default}` : ''}`;
		const t = param.kind.type;
		return `${param.name}${t.bounds.length ? `: ${t.bounds.map(boundText).join(' + ')}` : ''}${t.default ? ` = ${typeText(t.default)}` : ''}`;
	});
	return p.length ? `<${p.join(', ')}>` : '';
}

function functionSignature(name, sig, header = {}, params = []) {
	const inputs = sig.inputs.map(([arg, type]) => {
		if (arg === 'self' && type.generic === 'Self') return 'self';
		if (arg === 'self' && type.borrowed_ref?.type?.generic === 'Self') return `&${type.borrowed_ref.lifetime ? `${type.borrowed_ref.lifetime} ` : ''}${type.borrowed_ref.is_mutable ? 'mut ' : ''}self`;
		return `${arg}: ${typeText(type)}`;
	});
	if (sig.is_c_variadic) inputs.push('...');
	return `${header.is_const ? 'const ' : ''}${header.is_async ? 'async ' : ''}${header.is_unsafe ? 'unsafe ' : ''}fn ${name}${genericText(params)}(${inputs.join(', ')})${sig.output ? ` -> ${typeText(sig.output)}` : ''}`;
}

function whereText(generics) {
	const predicates = (generics?.where_predicates || []).map((predicate) => {
		if (predicate.bound_predicate) return `${typeText(predicate.bound_predicate.type)}: ${predicate.bound_predicate.bounds.map(boundText).join(' + ')}`;
		if (predicate.lifetime_predicate) return `${predicate.lifetime_predicate.lifetime}: ${predicate.lifetime_predicate.outlives.join(' + ')}`;
		if (predicate.eq_predicate) return `${typeText(predicate.eq_predicate.lhs)} = ${typeText(predicate.eq_predicate.rhs?.type)}`;
		throw new Error('Unsupported where predicate');
	});
	return predicates.length ? ` where ${predicates.join(', ')}` : '';
}

export function signature(item, index = {}) {
	const kind = kindOf(item), data = item.inner[kind], name = item.name || '';
	if (kind === 'function') return `${item.visibility === 'public' ? 'pub ' : ''}${functionSignature(name, data.sig, data.header, data.generics.params)}${whereText(data.generics)}`;
	if (kind === 'struct_field') return `${item.visibility === 'public' ? 'pub ' : ''}${name}: ${typeText(data)}`;
	if (kind === 'assoc_type') return `type ${name}${genericText(data.generics?.params || [])}${data.type ? ` = ${typeText(data.type)}` : ''}`;
	if (kind === 'assoc_const') return `const ${name}: ${typeText(data.type)}${data.value ? ` = ${data.value}` : ''}`;
	if (kind === 'type_alias') return `pub type ${name}${genericText(data.generics.params)} = ${typeText(data.type)}${whereText(data.generics)}`;
	if (kind === 'constant') return `pub const ${name}: ${typeText(data.type)} = ${data.const?.expr || '_'};`;
	if (kind === 'static') return `pub static ${data.is_mutable ? 'mut ' : ''}${name}: ${typeText(data.type)};`;
	if (kind === 'variant') {
		const fieldType = id => index[id]?.inner.struct_field ? typeText(index[id].inner.struct_field) : '_';
		const tuple = data.kind?.tuple;
		const fields = data.kind?.struct?.fields;
		return `${name}${tuple ? `(${tuple.map(fieldType).join(', ')})` : fields ? ` { ${fields.map(id => `${index[id]?.name || '_'}: ${fieldType(id)}`).join(', ')} }` : ''}${data.discriminant ? ` = ${data.discriminant.expr}` : ''}`;
	}
	if (kind === 'proc_macro') return `#[${data.kind === 'derive' ? 'derive' : 'proc_macro'}] ${name}`;
	if (kind === 'macro') return `macro_rules! ${name}`;
	if (['struct', 'enum', 'trait', 'union'].includes(kind)) return `pub ${kind} ${name}${genericText(data.generics?.params || [])}${whereText(data.generics)}`;
	if (kind === 'module') return `pub mod ${name}`;
	if (kind === 'reexport') return `pub use ${data.source}${data.source.split('::').at(-1) !== name ? ` as ${name}` : ''};`;
	return `pub ${kind} ${name}`;
}

function examplesFromDocs(docs, source, context) {
	const examples = [];
	for (const match of docs.matchAll(/^```([^\n]*)\n([\s\S]*?)^```\s*$/gm)) {
		if (!match[1] || /\brust\b/.test(match[1])) {
			const code = match[2].trimEnd();
			const exact = locateExample(code, source, context);
			examples.push({ code, source: exact || source, label: exact ? 'Example source lines' : 'Containing item source (example line span unavailable)' });
		}
	}
	return examples;
}

function locateExample(code, source, context) {
	if (!source || !context?.readSource) return null;
	const text = context.readSource(source.file);
	const lines = text.split('\n');
	const candidates = [];
	for (let i = 0; i < lines.length; i++) {
		const open = /^\s*\/\/(?:\/|!) ?(```[^\n]*)/.exec(lines[i]);
		if (!open) continue;
		const start = i;
		const body = [];
		while (++i < lines.length) {
			const content = /^\s*\/\/(?:\/|!) ?(.*)$/.exec(lines[i]);
			if (!content) break;
			if (/^```\s*$/.test(content[1])) {
				if (body.join('\n').trimEnd() === code) candidates.push({ start: start + 1, end: i + 1, inner: /^\s*\/\/!/.test(lines[start]) });
				break;
			}
			body.push(content[1]);
		}
	}
	// Exact text alone is insufficient: an identical example on an earlier
	// item must not become this item's source. Require attached doc comments.
	const attached = candidates.filter(candidate => candidate.end < source.lineStart && lines.slice(candidate.end, source.lineStart - 1).every(line => /^\s*(?:\/\/[\/!].*|#\[.*\]|)$/.test(line)));
	const crateDocs = candidates.filter(candidate => candidate.inner && source.lineStart === 1 && candidate.end <= source.lineEnd);
	const eligible = attached.length ? attached : crateDocs;
	const candidate = eligible.length === 1 ? eligible[0] : null;
	return candidate ? sourceLink({ filename: source.file, begin: [candidate.start, 1], end: [candidate.end, 1] }, context) : null;
}

export function buildReference(docs, context) {
	for (const doc of docs) if (doc.format_version !== FORMAT_VERSION) throw new Error(`Unsupported rustdoc JSON format ${doc.format_version}; expected ${FORMAT_VERSION}`);
	const facade = docs.find((doc) => doc.index[doc.root].name === context.crate);
	if (!facade) throw new Error('Facade rustdoc JSON not found');
	const canonical = new Map();
	for (const doc of docs) canonical.set(doc.index[doc.root].name, { doc, item: doc.index[doc.root] });
	for (const doc of docs) for (const [id, entry] of Object.entries(doc.paths)) if (doc.index[id]) canonical.set(entry.path.join('::'), { doc, item: doc.index[id] });
	function resolve(doc, id) {
		if (doc.index[id]) return { doc, item: doc.index[id] };
		return canonical.get(doc.paths[id]?.path.join('::')) || null;
	}
	// rustdoc may name a foreign item by a public alias rather than its defining path.
	let changed = true;
	while (changed) {
		changed = false;
		function aliases(doc, module, prefix, seen = new Set()) {
			const key = `${doc.index[doc.root].name}:${module.id}`;
			if (seen.has(key)) return;
			const next = new Set([...seen, key]);
			for (const id of module.inner.module.items) {
				const child = doc.index[id];
				if (!publicItem(child)) continue;
				const target = child.inner.use ? resolve(doc, child.inner.use.id) : { doc, item: child };
				if (!target || hidden(target.item)) continue;
				const targetPath = `${prefix}::${child.inner.use?.name || child.name}`;
				if (!canonical.has(targetPath)) { canonical.set(targetPath, target); changed = true; }
				if (target.item.inner.module) aliases(target.doc, target.item, child.inner.use?.is_glob ? prefix : targetPath, next);
			}
		}
		for (const doc of docs) aliases(doc, doc.index[doc.root], doc.index[doc.root].name);
	}
	const entries = new Map();
	function put(doc, item, publicPath, reexport = null) {
		if (hidden(item)) return;
		const key = `${doc.index[doc.root].name}:${item.id}`;
		const prior = entries.get(key);
		if (prior) { if (!prior.aliases.includes(publicPath)) prior.aliases.push(publicPath); return; }
		const kind = kindOf(item);
		let source = sourceLink(item.span, context);
		const reexportSource = reexport ? sourceLink(reexport.span, context) : null;
		const name = publicPath.split('::').at(-1);
		const slug = `${publicPath.split('::').slice(0, -1).map(slugPart).join('/')}/${kind.replaceAll('_', '-')}/${slugPart(name)}`;
		const page = { schemaVersion: 1, id: `${kind}:${publicPath}`, publicPath, kind, title: publicPath, signature: signature({ ...item, name }), docs: item.docs || '', source, reexportSource, aliases: [], members: [], examples: examplesFromDocs(item.docs || '', source, context), docsDigest: sha256(item.docs || '') };
		entries.set(key, page);
		const inner = item.inner[kind];
		const memberIds = kind === 'enum' ? inner.variants : kind === 'trait' ? inner.items : inner?.kind?.plain?.fields || inner?.kind?.tuple?.filter(id => id !== null) || inner?.fields || [];
		for (const id of memberIds || []) {
			const member = doc.index[id];
			if (!member || hidden(member) || (kind !== 'enum' && kind !== 'trait' && member.visibility !== 'public')) continue;
			page.members.push(memberRecord(member, `${publicPath}::${member.name}`, context, doc.index));
		}
		for (const implId of inner.impls || []) {
			const impl = doc.index[implId]?.inner.impl;
			if (!impl || impl.is_synthetic || impl.blanket_impl) continue;
			for (const id of impl.items || []) {
				const member = doc.index[id];
				if (!member || hidden(member) || (!impl.trait && member.visibility !== 'public')) continue;
				if (impl.trait && !member.docs && !member.span) continue;
				const record = memberRecord(member, `${publicPath}::${member.name}`, context, doc.index);
				if (impl.trait) record.trait = impl.trait.path;
				page.members.push(record);
			}
		}
		page.members.sort((a, b) => a.publicPath < b.publicPath ? -1 : a.publicPath > b.publicPath ? 1 : 0);
		page.slug = slug;
	}
	function walk(doc, module, publicPath, ancestors = new Set()) {
		const identity = `${doc.index[doc.root].name}:${module.id}`;
		if (ancestors.has(identity)) return;
		const next = new Set([...ancestors, identity]);
		if (publicPath !== context.crate) put(doc, module, publicPath);
		const children = module.inner.module.items.map((id) => doc.index[id]).filter(publicItem);
		// Prefer direct facade exports over longer prelude aliases.
		const isPrelude = item => (item.name || item.inner.use?.name) === 'prelude';
		children.sort((a, b) => Number(isPrelude(a)) - Number(isPrelude(b)) || (kindOf(a) === 'module') - (kindOf(b) === 'module'));
		for (const child of children) {
			if (child.inner.use) {
				const use = child.inner.use;
				const target = resolve(doc, use.id);
				if (target && !hidden(target.item)) {
					const targetPath = `${publicPath}::${use.name}`;
					if (target.item.inner.module) walk(target.doc, target.item, use.is_glob ? publicPath : targetPath, next);
					else put(target.doc, target.item, targetPath, child);
				} else {
					const name = use.name;
					put(doc, { ...child, name, docs: child.docs || '', inner: { reexport: { source: use.source } } }, `${publicPath}::${name}`);
				}
			} else if (child.inner.module) walk(doc, child, `${publicPath}::${child.name}`, next);
			else put(doc, child, `${publicPath}::${child.name}`);
		}
	}
	function memberRecord(member, publicPath, ctx, index) {
		const source = sourceLink(member.span, ctx);
		return { id: `${kindOf(member)}:${publicPath}`, publicPath, title: publicPath, kind: kindOf(member), signature: signature(member, index), docs: member.docs || '', source, examples: examplesFromDocs(member.docs || '', source, ctx) };
	}
	walk(facade, facade.index[facade.root], context.crate);
	const pages = Object.fromEntries([...entries.values()].sort((a, b) => a.slug < b.slug ? -1 : a.slug > b.slug ? 1 : 0).map((page) => [page.slug, page]));
	const root = facade.index[facade.root];
	pages.index = { schemaVersion: 1, id: `module:${context.crate}`, publicPath: context.crate, title: `${context.crate} Rust API`, kind: 'module', signature: `pub crate ${context.crate}`, docs: root.docs || '', docsDigest: sha256(root.docs || ''), source: sourceLink(root.span, context), aliases: [], members: Object.values(pages).map(page => ({ id: page.id, publicPath: page.publicPath, title: page.title, kind: page.kind, signature: page.signature, docs: '', source: page.source, examples: [] })), examples: examplesFromDocs(root.docs || '', sourceLink(root.span, context), context) };
	return pages;
}
