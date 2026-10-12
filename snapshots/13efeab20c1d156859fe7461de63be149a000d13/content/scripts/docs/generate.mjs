#!/usr/bin/env node

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { TextDecoder } from 'node:util';

export const SCHEMA_VERSION = 1;
export const PUBLIC_ROOT = 'docs/public';
const MAX_FILE_BYTES = 16 * 1024 * 1024;
const MAX_TOTAL_BYTES = 64 * 1024 * 1024;
const HEX_40 = /^[0-9a-f]{40}$/;
const HEX_64 = /^[0-9a-f]{64}$/;
const RELEASE_METADATA_FIELDS = new Set(['version', 'date', 'channel', 'previous']);
const VERSION = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;
const utf8 = new TextDecoder('utf-8', { fatal: true });

function fail(message) {
  throw new Error(message);
}

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function parseVersion(value) {
  if (typeof value !== 'string' || !VERSION.test(value)) {
    fail(`invalid version ${JSON.stringify(value)}; expected a semantic version`);
  }
  return value;
}

function parseRepository(value) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.-]*\/[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(value)) {
    fail(`invalid repository ${JSON.stringify(value)}; expected Owner/Repo`);
  }
  return value;
}

function parseCommit(value, label = 'commit') {
  if (typeof value !== 'string' || !HEX_40.test(value)) {
    fail(`${label} must be a full 40-character Git commit ID`);
  }
  return value;
}

function decodeUtf8(bytes, label) {
  try {
    return utf8.decode(bytes);
  } catch {
    fail(`${label} is not valid UTF-8`);
  }
}

function splitNulBuffer(buffer) {
  const entries = [];
  let start = 0;
  for (let index = 0; index < buffer.length; index += 1) {
    if (buffer[index] === 0) {
      entries.push(buffer.subarray(start, index));
      start = index + 1;
    }
  }
  if (start !== buffer.length) fail('Git returned a malformed NUL-delimited tree');
  return entries.filter((entry) => entry.length > 0);
}

function parseTreeEntries(buffer) {
  return splitNulBuffer(buffer).map((entry) => {
    const tab = entry.indexOf(9);
    if (tab < 0) fail('Git returned a malformed tree entry');
    const header = entry.subarray(0, tab).toString('ascii').split(' ');
    if (header.length !== 3) fail('Git returned a malformed tree header');
    const [mode, type, oid] = header;
    const file = decodeUtf8(entry.subarray(tab + 1), 'Git path');
    return { mode, type, oid, file };
  });
}

function isExcludedPath(relativePath) {
  return relativePath.split('/').some((segment) => {
    const lower = segment.toLowerCase();
    return segment.startsWith('_') || lower === 'agents.md' || lower === 'readme.md';
  });
}

function validateRelativePath(relativePath) {
  if (typeof relativePath !== 'string' || relativePath.length === 0) fail('public paths must not be empty');
  if (relativePath.startsWith('/') || relativePath.includes('\\') || relativePath.includes('%')) {
    fail(`unsafe public path ${JSON.stringify(relativePath)}`);
  }
  if (/[\u0000-\u001f\u007f]/.test(relativePath)) fail(`control character in public path ${JSON.stringify(relativePath)}`);
  const segments = relativePath.split('/');
  if (segments.some((segment) => segment.length === 0 || segment === '.' || segment === '..')) {
    fail(`traversal or empty segment in public path ${JSON.stringify(relativePath)}`);
  }
  return relativePath;
}

function routeSlug(segment) {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(segment)) {
    fail(`route segment ${JSON.stringify(segment)} must already be lowercase kebab case`);
  }
  return segment;
}

function pageRoute(relativePath, extension) {
  const withoutExtension = relativePath.slice(0, -extension.length);
  const rawSegments = withoutExtension.split('/');
  const leaf = rawSegments.at(-1);
  if (leaf === 'index') rawSegments.pop();
  const segments = rawSegments.map(routeSlug);
  return segments.length === 0 ? '/' : `/${segments.join('/')}`;
}

function titleFromRoute(route) {
  if (route === '/') return 'Home';
  const segment = route.split('/').at(-1) ?? 'Home';
  return segment.split('-').map((word) => word.length === 0 ? word : `${word[0].toUpperCase()}${word.slice(1)}`).join(' ');
}

function stripYamlComment(value) {
  let quote = null;
  let escaped = false;
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (quote === '"' && character === '\\' && !escaped) {
      escaped = true;
      continue;
    }
    if (quote === '"' && character === '"' && !escaped) quote = null;
    else if (quote === "'" && character === "'") {
      if (value[index + 1] === "'") index += 1;
      else quote = null;
    } else if (quote === null && (character === '"' || character === "'")) quote = character;
    else if (quote === null && character === '#' && (index === 0 || /\s/.test(value[index - 1]))) return value.slice(0, index).trimEnd();
    escaped = character === '\\' && !escaped;
  }
  return value.trimEnd();
}

function parseStringScalar(raw, key) {
  const value = stripYamlComment(raw).trim();
  if (value.length === 0) fail(`frontmatter ${key} must be a non-empty string`);
  if (value.startsWith('"')) {
    try {
      const parsed = JSON.parse(value);
      if (typeof parsed !== 'string' || parsed.length === 0) fail(`frontmatter ${key} must be a non-empty string`);
      return parsed;
    } catch (error) {
      if (error instanceof Error && error.message.includes('frontmatter')) throw error;
      fail(`frontmatter ${key} has an invalid JSON-style quoted string`);
    }
  }
  if (value.startsWith("'")) {
    if (!/^'(?:[^']|'')*'$/.test(value)) fail(`frontmatter ${key} has an invalid single-quoted string`);
    const parsed = value.slice(1, -1).replace(/''/g, "'");
    if (parsed.length === 0) fail(`frontmatter ${key} must be a non-empty string`);
    return parsed;
  }
  if (/^[&*!|>@{}[\]`]|^(?:-|\?|:)\s/.test(value) || value.includes('\t')) {
    fail(`frontmatter ${key} uses unsupported YAML syntax; quote this scalar`);
  }
  return value;
}

function isReleaseSourcePage(file) {
  return file.startsWith('releases/') || file.startsWith(`${PUBLIC_ROOT}/releases/`);
}

export function parseFrontmatter(source, file = '<page>') {
  const normalized = source.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
  const lines = normalized.split('\n');
  if (lines[0] !== '---') return { metadata: {}, body: source };
  const end = lines.indexOf('---', 1);
  if (end < 0) fail(`${file}: frontmatter has no closing --- line`);

  const metadata = {};
  for (let index = 1; index < end; index += 1) {
    const line = lines[index];
    if (line.trim().length === 0 || line.trimStart().startsWith('#')) continue;
    const match = /^(title|description|version|date|channel|previous|order|draft):(?:\s*)(.*)$/.exec(line);
    if (!match) fail(`${file}:${index + 1}: unsupported or malformed frontmatter field`);
    const [, key, raw] = match;
    if (Object.hasOwn(metadata, key)) fail(`${file}:${index + 1}: duplicate frontmatter field ${key}`);
    if (RELEASE_METADATA_FIELDS.has(key) && file !== '<page>' && !isReleaseSourcePage(file)) {
      fail(`${file}:${index + 1}: release metadata is only allowed under releases/`);
    }
    if (
      key === 'title' ||
      key === 'description' ||
      key === 'version' ||
      key === 'date' ||
      key === 'channel' ||
      key === 'previous'
    ) {
      metadata[key] = parseStringScalar(raw, key);
    } else if (key === 'order') {
      const value = stripYamlComment(raw).trim();
      if (!/^(0|[1-9]\d*)$/.test(value)) fail(`${file}:${index + 1}: order must be a non-negative integer`);
      const order = Number(value);
      if (!Number.isSafeInteger(order)) fail(`${file}:${index + 1}: order is too large`);
      metadata.order = order;
    } else {
      const value = stripYamlComment(raw).trim();
      if (value !== 'true' && value !== 'false') fail(`${file}:${index + 1}: draft must be true or false`);
      metadata.draft = value === 'true';
    }
  }
  return { metadata, body: lines.slice(end + 1).join('\n') };
}

function titleFromBody(body) {
  for (const line of body.split('\n')) {
    const match = /^ {0,3}#\s+(.+?)\s*#*\s*$/.exec(line);
    if (match) return match[1].replace(/[`*_]/g, '').trim();
  }
  return undefined;
}

function checkSafeMdx(body, file) {
  let fence = null;
  let calloutOpen = false;
  const lines = body.split('\n');
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    const fenceOpen = /^ {0,3}(`{3,}|~{3,})/.exec(line);
    if (fence !== null) {
      if (fenceOpen && fenceOpen[1][0] === fence.marker && fenceOpen[1].length >= fence.length && /^ {0,3}(?:`{3,}|~{3,})\s*$/.test(line)) fence = null;
      continue;
    }
    if (fenceOpen) {
      fence = { marker: fenceOpen[1][0], length: fenceOpen[1].length };
      continue;
    }
    if (/^\s*(?:import|export)\b/.test(line)) fail(`${file}:${index + 1}: MDX imports and exports are not supported`);
    if (/[{}]/.test(line)) fail(`${file}:${index + 1}: MDX expressions are not supported`);
    const calloutStart = /^\s*<Callout title=(?:"[^"<>]*"|'[^'<>]*')>\s*$/.test(line);
    if (calloutStart) {
      if (calloutOpen) fail(`${file}:${index + 1}: nested Callout blocks are not supported`);
      calloutOpen = true;
      continue;
    }
    if (trimmed === '</Callout>') {
      if (!calloutOpen) fail(`${file}:${index + 1}: unmatched Callout closing tag`);
      calloutOpen = false;
      continue;
    }
    if (/[<>]/.test(line)) fail(`${file}:${index + 1}: only line-delimited Callout JSX is supported in MDX`);
  }
  if (calloutOpen) fail(`${file}: Callout block has no closing tag`);
}

function buildManifestEntries(entries) {
  const pages = Object.create(null);
  const assets = Object.create(null);
  const foldedAssets = new Map();
  let totalBytes = 0;

  for (const entry of entries) {
    const relativePath = validateRelativePath(entry.file);
    if (isExcludedPath(relativePath)) continue;
    if (entry.mode === '120000') fail(`${relativePath}: symbolic links are not allowed in docs/public`);
    if (entry.type !== 'blob' || (entry.mode !== '100644' && entry.mode !== '100755')) {
      fail(`${relativePath}: only regular files are allowed in docs/public`);
    }
    if (!Buffer.isBuffer(entry.bytes)) fail(`${relativePath}: missing file bytes`);
    if (entry.bytes.length > MAX_FILE_BYTES) fail(`${relativePath}: exceeds the ${MAX_FILE_BYTES}-byte file limit`);
    totalBytes += entry.bytes.length;
    if (totalBytes > MAX_TOTAL_BYTES) fail(`docs/public exceeds the ${MAX_TOTAL_BYTES}-byte total limit`);

    const extensionMatch = /\.(md|mdx)$/i.exec(relativePath);
    if (extensionMatch) {
      const extension = extensionMatch[0].toLowerCase();
      if (extension !== extensionMatch[0]) fail(`${relativePath}: page extensions must be lowercase .md or .mdx`);
      const format = extension === '.mdx' ? 'mdx' : 'markdown';
      const source = decodeUtf8(entry.bytes, relativePath);
      const { metadata, body } = parseFrontmatter(source, relativePath);
      if (metadata.draft === true) continue;
      if (format === 'mdx') checkSafeMdx(body, relativePath);
      const route = pageRoute(relativePath, extensionMatch[0]);
      if (Object.hasOwn(pages, route)) fail(`route collision at ${route}: ${pages[route].file} and ${relativePath}`);
      const title = metadata.title ?? titleFromBody(body) ?? titleFromRoute(route);
      const page = {
        file: relativePath,
        title,
        ...(metadata.description === undefined ? {} : { description: metadata.description }),
        ...(metadata.version === undefined ? {} : { version: metadata.version }),
        ...(metadata.date === undefined ? {} : { date: metadata.date }),
        ...(metadata.channel === undefined ? {} : { channel: metadata.channel }),
        ...(metadata.previous === undefined ? {} : { previous: metadata.previous }),
        order: metadata.order ?? 0,
        format,
        sha256: sha256(entry.bytes),
      };
      pages[route] = page;
      continue;
    }

    if (!relativePath.startsWith('assets/')) fail(`${relativePath}: non-page files must be under assets/`);
    if (relativePath.split('/').some((segment, index) => index > 0 && !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(segment))) {
      fail(`${relativePath}: asset path segments must use ASCII letters, digits, dots, underscores, or hyphens`);
    }
    const folded = relativePath.toLowerCase();
    if (foldedAssets.has(folded)) fail(`asset path collision: ${foldedAssets.get(folded)} and ${relativePath}`);
    foldedAssets.set(folded, relativePath);
    assets[relativePath] = { sha256: sha256(entry.bytes) };
  }

  if (Object.keys(pages).length === 0) fail('docs/public must contain at least one non-draft Markdown or MDX page');
  if (!Object.hasOwn(pages, '/')) fail('docs/public requires a root index.md or index.mdx');
  const sortedPages = Object.fromEntries(Object.entries(pages).sort(([left], [right]) => compareText(left, right)));
  const sortedAssets = Object.fromEntries(Object.entries(assets).sort(([left], [right]) => compareText(left, right)));
  return { pages: sortedPages, assets: sortedAssets };
}

function git(root, args, options = {}) {
  try {
    return execFileSync('git', args, {
      cwd: root,
      encoding: options.encoding,
      maxBuffer: MAX_TOTAL_BYTES + 1024 * 1024,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch (error) {
    const stderr = error?.stderr ? decodeUtf8(Buffer.from(error.stderr), 'git stderr').trim() : '';
    fail(`git ${args[0]} failed${stderr ? `: ${stderr}` : ''}`);
  }
}

function findGitRoot(cwd) {
  return String(git(cwd, ['rev-parse', '--show-toplevel'], { encoding: 'utf8' })).trim();
}

function resolveGitCommit(root, ref) {
  if (typeof ref !== 'string' || ref.length === 0) fail('source ref must not be empty');
  const commit = String(git(root, ['rev-parse', '--verify', '--end-of-options', `${ref}^{commit}`], { encoding: 'utf8' })).trim().toLowerCase();
  return parseCommit(commit, 'resolved source commit');
}

function collectGitSnapshot(root, commit) {
  const rootEntries = parseTreeEntries(git(root, ['ls-tree', '-z', '--full-tree', commit, '--', PUBLIC_ROOT]));
  if (rootEntries.length !== 1 || rootEntries[0].file !== PUBLIC_ROOT || rootEntries[0].type !== 'tree' || rootEntries[0].mode !== '040000') {
    fail(`${commit} does not contain ${PUBLIC_ROOT} as a regular directory`);
  }
  const treeEntries = parseTreeEntries(git(root, ['ls-tree', '-r', '-z', '--full-tree', commit, '--', PUBLIC_ROOT]));
  const records = [];
  let totalBytes = 0;
  for (const entry of treeEntries) {
    if (!entry.file.startsWith(`${PUBLIC_ROOT}/`)) fail(`Git returned a path outside ${PUBLIC_ROOT}`);
    const file = entry.file.slice(PUBLIC_ROOT.length + 1);
    if (isExcludedPath(file)) continue;
    validateRelativePath(file);
    if (entry.mode === '120000') {
      records.push({ ...entry, file, bytes: Buffer.alloc(0) });
      continue;
    }
    if (entry.type !== 'blob' || (entry.mode !== '100644' && entry.mode !== '100755')) {
      records.push({ ...entry, file, bytes: Buffer.alloc(0) });
      continue;
    }
    const sizeText = String(git(root, ['cat-file', '-s', entry.oid], { encoding: 'utf8' })).trim();
    if (!/^(0|[1-9]\d*)$/.test(sizeText)) fail(`${file}: Git returned an invalid blob size`);
    const size = Number(sizeText);
    if (!Number.isSafeInteger(size) || size > MAX_FILE_BYTES) fail(`${file}: exceeds the ${MAX_FILE_BYTES}-byte file limit`);
    totalBytes += size;
    if (totalBytes > MAX_TOTAL_BYTES) fail(`docs/public exceeds the ${MAX_TOTAL_BYTES}-byte total limit`);
    const bytes = git(root, ['cat-file', 'blob', entry.oid]);
    if (bytes.length !== size) fail(`${file}: Git returned an unexpected blob size`);
    records.push({ ...entry, file, bytes });
  }
  return records;
}

function collectDirectory(root) {
  const absoluteRoot = path.resolve(root);
  let rootStat;
  try {
    rootStat = fs.lstatSync(absoluteRoot);
  } catch {
    fail(`public root does not exist: ${absoluteRoot}`);
  }
  if (rootStat.isSymbolicLink() || !rootStat.isDirectory()) fail(`public root must be a real directory: ${absoluteRoot}`);
  const records = [];
  let totalBytes = 0;

  function walk(directory, relativeDirectory) {
    const children = fs.readdirSync(directory, { withFileTypes: true }).sort((left, right) => compareText(left.name, right.name));
    for (const child of children) {
      const relativePath = relativeDirectory ? `${relativeDirectory}/${child.name}` : child.name;
      if (isExcludedPath(relativePath)) continue;
      validateRelativePath(relativePath);
      const absolutePath = path.join(directory, child.name);
      const stat = fs.lstatSync(absolutePath);
      if (stat.isSymbolicLink()) fail(`${relativePath}: symbolic links are not allowed in docs/public`);
      if (stat.isDirectory()) {
        walk(absolutePath, relativePath);
      } else if (stat.isFile()) {
        if (stat.size > MAX_FILE_BYTES) fail(`${relativePath}: exceeds the ${MAX_FILE_BYTES}-byte file limit`);
        totalBytes += stat.size;
        if (totalBytes > MAX_TOTAL_BYTES) fail(`docs/public exceeds the ${MAX_TOTAL_BYTES}-byte total limit`);
        const bytes = fs.readFileSync(absolutePath);
        if (bytes.length !== stat.size) fail(`${relativePath}: file changed while previewing`);
        records.push({ mode: (stat.mode & 0o111) === 0 ? '100644' : '100755', type: 'blob', file: relativePath, bytes });
      } else {
        fail(`${relativePath}: only regular files are allowed in docs/public`);
      }
    }
  }
  walk(absoluteRoot, '');
  return records;
}

function normalizeSchemaVersion(value) {
  const version = typeof value === 'number'
    ? value
    : (typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : Number.NaN);
  if (version !== SCHEMA_VERSION) fail(`unsupported schema version ${JSON.stringify(value)}; this generator supports ${SCHEMA_VERSION}`);
  return version;
}

function makeManifest({ version, repository, commit, entries, preview }) {
  const normalizedVersion = parseVersion(version);
  const normalizedRepository = parseRepository(repository);
  const normalizedCommit = parseCommit(commit, 'source commit');
  const collected = buildManifestEntries(entries);
  return {
    schemaVersion: SCHEMA_VERSION,
    version: normalizedVersion,
    source: { repository: normalizedRepository, commit: normalizedCommit, root: PUBLIC_ROOT },
    pages: collected.pages,
    assets: collected.assets,
    ...(preview ? { preview: true } : {}),
  };
}

export function generatePreview({ root, version, repository, sourceCommit, schemaVersion = SCHEMA_VERSION }) {
  normalizeSchemaVersion(schemaVersion);
  const commit = parseCommit(sourceCommit, 'preview source commit');
  const entries = collectDirectory(root);
  return makeManifest({ version, repository, commit, entries, preview: true });
}

export function generateFromGit({ cwd = process.cwd(), source, version, repository, schemaVersion = SCHEMA_VERSION }) {
  normalizeSchemaVersion(schemaVersion);
  const root = findGitRoot(path.resolve(cwd));
  const commit = resolveGitCommit(root, source);
  const entries = collectGitSnapshot(root, commit);
  return makeManifest({ version, repository, commit, entries, preview: false });
}

function stableJson(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function isWithin(parent, child) {
  const relative = path.relative(parent, child);
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}

function ensureOutputOutsideSource(outputDirectory, sourceRoot) {
  function resolveThroughExistingParents(candidate) {
    let current = path.resolve(candidate);
    const missing = [];
    while (true) {
      try {
        return path.join(fs.realpathSync(current), ...missing.reverse());
      } catch {
        const parent = path.dirname(current);
        if (parent === current) return path.resolve(candidate);
        missing.push(path.basename(current));
        current = parent;
      }
    }
  }
  const resolvedSource = resolveThroughExistingParents(sourceRoot);
  const resolvedOutput = resolveThroughExistingParents(outputDirectory);
  if (isWithin(resolvedSource, resolvedOutput)) fail(`output directory must be outside the selected source root (${resolvedSource})`);
}

function manifestIdentity(manifest) {
  return JSON.stringify({ version: manifest.version, source: manifest.source, preview: manifest.preview === true });
}

export function writeManifest(manifest, outputDirectory, sourceRoot) {
  validateManifest(manifest);
  ensureOutputOutsideSource(outputDirectory, sourceRoot);
  const output = path.resolve(outputDirectory);
  fs.mkdirSync(output, { recursive: true });
  const outputFile = path.join(output, 'manifest.json');
  const bytes = Buffer.from(stableJson(manifest));
  if (fs.existsSync(outputFile)) {
    const stat = fs.lstatSync(outputFile);
    if (stat.isSymbolicLink() || !stat.isFile()) fail(`refusing to replace non-file manifest output ${outputFile}`);
    let oldBytes;
    let oldManifest;
    try {
      oldBytes = fs.readFileSync(outputFile);
      oldManifest = JSON.parse(decodeUtf8(oldBytes, outputFile));
    } catch {
      fail(`refusing to replace unreadable existing manifest ${outputFile}`);
    }
    if (manifestIdentity(oldManifest) !== manifestIdentity(manifest)) {
      fail(`refusing to replace manifest with a conflicting release identity at ${outputFile}`);
    }
    if (oldBytes.equals(bytes)) return { outputFile, sha256: sha256(bytes), changed: false };
    if (manifest.preview !== true || oldManifest.preview !== true) {
      fail(`refusing to change an existing release manifest at ${outputFile}`);
    }
  }
  const temporary = path.join(output, `.manifest-${process.pid}-${crypto.randomBytes(6).toString('hex')}.tmp`);
  try {
    fs.writeFileSync(temporary, bytes, { flag: 'wx', mode: 0o644 });
    fs.renameSync(temporary, outputFile);
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
  return { outputFile, sha256: sha256(bytes), changed: true };
}

function assertSafeArtifactPath(value) {
  if (typeof value !== 'string' || value.length === 0 || value.startsWith('/') || value.includes('\\') || value.includes('%') || /[?#\u0000-\u0020\u007f]/.test(value)) {
    fail(`invalid artifact path ${JSON.stringify(value)}`);
  }
  const segments = value.split('/');
  if (segments.some((segment) => segment.length === 0 || segment === '.' || segment === '..')) fail(`invalid artifact path ${JSON.stringify(value)}`);
  return value;
}

export function validateManifest(manifest, { allowPreview = true } = {}) {
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) fail('manifest must be a JSON object');
  const allowedManifestKeys = new Set(['schemaVersion', 'version', 'source', 'pages', 'assets', 'preview']);
  if (Object.keys(manifest).some((key) => !allowedManifestKeys.has(key))) fail('manifest contains unsupported top-level fields');
  if (manifest.schemaVersion !== SCHEMA_VERSION) fail(`unsupported manifest schemaVersion ${JSON.stringify(manifest.schemaVersion)}`);
  parseVersion(manifest.version);
  if (!manifest.source || typeof manifest.source !== 'object' || Array.isArray(manifest.source)) fail('manifest source must be an object');
  if (Object.keys(manifest.source).some((key) => !['repository', 'commit', 'root'].includes(key))) fail('manifest source contains unsupported fields');
  parseRepository(manifest.source.repository);
  parseCommit(manifest.source.commit, 'manifest source.commit');
  if (manifest.source.root !== PUBLIC_ROOT) fail(`manifest source.root must be ${PUBLIC_ROOT}`);
  if (!manifest.pages || typeof manifest.pages !== 'object' || Array.isArray(manifest.pages)) fail('manifest pages must be an object');
  if (!manifest.assets || typeof manifest.assets !== 'object' || Array.isArray(manifest.assets)) fail('manifest assets must be an object');
  if (Object.keys(manifest.pages).length === 0) fail('manifest must contain at least one page');
  if (!Object.hasOwn(manifest.pages, '/')) fail('manifest requires a root index page');
  const pageFiles = new Set();
  for (const [route, page] of Object.entries(manifest.pages)) {
    if (route !== '/' && !/^\/(?:[a-z0-9]+(?:-[a-z0-9]+)*)(?:\/[a-z0-9]+(?:-[a-z0-9]+)*)*$/.test(route)) {
      fail(`invalid manifest page route ${JSON.stringify(route)}`);
    }
    if (!page || typeof page !== 'object' || Array.isArray(page)) fail(`manifest page ${route} must be an object`);
    const allowedPageKeys = new Set(['file', 'title', 'description', 'version', 'date', 'channel', 'previous', 'order', 'format', 'sha256']);
    if (Object.keys(page).some((key) => !allowedPageKeys.has(key))) fail(`manifest page ${route} contains unsupported fields`);
    validateRelativePath(page.file);
    if (isExcludedPath(page.file)) fail(`manifest page ${route} refers to an excluded file`);
    if ([...RELEASE_METADATA_FIELDS].some((field) => Object.hasOwn(page, field)) && !page.file.startsWith('releases/')) {
      fail(`manifest page ${route} release metadata is only allowed under releases/`);
    }
    const extension = /\.(md|mdx)$/.exec(page.file)?.[1];
    if (extension === undefined) fail(`manifest page ${route} file must end in lowercase .md or .mdx`);
    const expectedFormat = extension === 'mdx' ? 'mdx' : 'markdown';
    if (page.format !== expectedFormat) fail(`manifest page ${route} format does not match its file extension`);
    const expectedRoute = pageRoute(page.file, `.${extension}`);
    if (route !== expectedRoute) fail(`manifest page ${route} does not match its source file route ${expectedRoute}`);
    if (pageFiles.has(page.file)) fail(`manifest contains duplicate page file ${page.file}`);
    pageFiles.add(page.file);
    if (typeof page.title !== 'string' || page.title.length === 0) fail(`manifest page ${route} needs a title`);
    if (page.description !== undefined && typeof page.description !== 'string') fail(`manifest page ${route} description must be a string`);
    for (const field of ['version', 'date', 'channel', 'previous']) {
      if (Object.hasOwn(page, field) && (typeof page[field] !== 'string' || page[field].length === 0)) {
        fail(`manifest page ${route} ${field} must be a non-empty string`);
      }
    }
    if (!Number.isSafeInteger(page.order) || page.order < 0) fail(`manifest page ${route} order must be a non-negative integer`);
    if (page.format !== 'markdown' && page.format !== 'mdx') fail(`manifest page ${route} has unsupported format`);
    if (typeof page.sha256 !== 'string' || !HEX_64.test(page.sha256)) fail(`manifest page ${route} has an invalid SHA-256`);
  }
  const foldedAssets = new Set();
  for (const [assetPath, asset] of Object.entries(manifest.assets)) {
    assertSafeArtifactPath(assetPath);
    if (!assetPath.startsWith('assets/')) fail(`manifest asset ${assetPath} must be under assets/`);
    if (isExcludedPath(assetPath)) fail(`manifest asset ${assetPath} refers to an excluded file`);
    if (assetPath.split('/').some((segment, index) => index > 0 && !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(segment))) {
      fail(`manifest asset ${assetPath} contains an unsafe path segment`);
    }
    const folded = assetPath.toLowerCase();
    if (foldedAssets.has(folded)) fail(`manifest contains an asset path collision at ${assetPath}`);
    foldedAssets.add(folded);
    if (!asset || typeof asset !== 'object' || typeof asset.sha256 !== 'string' || !HEX_64.test(asset.sha256)) fail(`manifest asset ${assetPath} has an invalid SHA-256`);
    if (Object.keys(asset).some((key) => key !== 'sha256')) fail(`manifest asset ${assetPath} contains unsupported fields`);
  }
  if (manifest.preview !== undefined && manifest.preview !== true) fail('manifest preview marker must be true when present');
  if (!allowPreview && manifest.preview === true) fail('preview manifests cannot be added to a release catalog');
  return manifest;
}

function validateCatalog(catalog) {
  if (!catalog || typeof catalog !== 'object' || Array.isArray(catalog)) fail('catalog must be a JSON object');
  if (Object.keys(catalog).some((key) => !['schemaVersion', 'latest', 'versions'].includes(key))) fail('catalog contains unsupported top-level fields');
  if (catalog.schemaVersion !== SCHEMA_VERSION) fail(`unsupported catalog schemaVersion ${JSON.stringify(catalog.schemaVersion)}`);
  parseVersion(catalog.latest);
  if (!catalog.versions || typeof catalog.versions !== 'object' || Array.isArray(catalog.versions)) fail('catalog versions must be an object');
  for (const [version, entry] of Object.entries(catalog.versions)) {
    parseVersion(version);
    if (!entry || typeof entry !== 'object' || !entry.manifest || typeof entry.manifest !== 'object') fail(`catalog version ${version} needs a manifest pointer`);
    if (Array.isArray(entry) || Object.keys(entry).some((key) => key !== 'manifest')) fail(`catalog version ${version} contains unsupported fields`);
    parseRepository(entry.manifest.repository);
    parseCommit(entry.manifest.commit, `catalog ${version} artifact commit`);
    assertSafeArtifactPath(entry.manifest.path);
    if (Object.keys(entry.manifest).some((key) => !['repository', 'commit', 'path', 'sha256'].includes(key))) fail(`catalog version ${version} manifest pointer contains unsupported fields`);
    if (entry.manifest.path !== `versions/${version}/manifest.json`) fail(`catalog version ${version} has a non-canonical manifest path`);
    if (typeof entry.manifest.sha256 !== 'string' || !HEX_64.test(entry.manifest.sha256)) fail(`catalog ${version} has an invalid manifest SHA-256`);
  }
  if (!Object.hasOwn(catalog.versions, catalog.latest)) fail(`catalog latest ${catalog.latest} has no version entry`);
  return catalog;
}

function parseJsonBytes(bytes, label) {
  try {
    return JSON.parse(decodeUtf8(bytes, label));
  } catch (error) {
    if (error instanceof Error && error.message.startsWith(`${label} is not valid UTF-8`)) throw error;
    fail(`${label} is not valid JSON`);
  }
}

function catalogSerialization(catalog) {
  const versions = Object.fromEntries(Object.entries(catalog.versions).sort(([left], [right]) => compareText(left, right)));
  return stableJson({ schemaVersion: SCHEMA_VERSION, latest: catalog.latest, versions });
}

function canonicalizeJson(value) {
  if (Array.isArray(value)) return value.map(canonicalizeJson);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value)
      .sort(([left], [right]) => compareText(left, right))
      .map(([key, nested]) => [key, canonicalizeJson(nested)]));
  }
  return value;
}

function sameJson(left, right) {
  return JSON.stringify(canonicalizeJson(left)) === JSON.stringify(canonicalizeJson(right));
}

function readGitBlob(checkout, commit, relativePath) {
  const safePath = assertSafeArtifactPath(relativePath);
  const root = findGitRoot(path.resolve(checkout));
  const normalizedCommit = parseCommit(commit, 'artifact commit');
  const entries = parseTreeEntries(git(root, ['ls-tree', '-z', '--full-tree', normalizedCommit, '--', safePath]));
  if (entries.length !== 1 || entries[0].file !== safePath || entries[0].type !== 'blob' || !['100644', '100755'].includes(entries[0].mode)) {
    fail(`artifact Git commit ${normalizedCommit} does not contain ${safePath} as a regular file`);
  }
  return git(root, ['cat-file', 'blob', entries[0].oid]);
}

function atomicWrite(filePath, bytes) {
  const absolute = path.resolve(filePath);
  fs.mkdirSync(path.dirname(absolute), { recursive: true });
  if (fs.existsSync(absolute)) {
    const stat = fs.lstatSync(absolute);
    if (stat.isSymbolicLink() || !stat.isFile()) fail(`refusing to replace non-file ${absolute}`);
  }
  const temporary = path.join(path.dirname(absolute), `.${path.basename(absolute)}-${process.pid}-${crypto.randomBytes(6).toString('hex')}.tmp`);
  try {
    fs.writeFileSync(temporary, bytes, { flag: 'wx', mode: 0o644 });
    fs.renameSync(temporary, absolute);
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
}

export function addCatalogVersion({
  catalogPath,
  manifestPath,
  repository,
  artifactCommit,
  sourceCwd = process.cwd(),
  artifactCwd = process.cwd(),
}) {
  const normalizedRepository = parseRepository(repository);
  const normalizedCommit = parseCommit(artifactCommit, 'artifact commit');
  const manifestBytes = fs.readFileSync(manifestPath);
  const manifest = validateManifest(parseJsonBytes(manifestBytes, manifestPath), { allowPreview: false });
  const version = manifest.version;
  const artifactPath = `versions/${version}/manifest.json`;
  const sourceManifest = generateFromGit({
    cwd: sourceCwd,
    source: manifest.source.commit,
    repository: manifest.source.repository,
    version,
  });
  if (!sameJson(sourceManifest, manifest)) fail(`manifest content does not match the selected source Git commit ${manifest.source.commit}`);
  const artifactBytes = readGitBlob(artifactCwd, normalizedCommit, artifactPath);
  if (!artifactBytes.equals(manifestBytes)) fail(`manifest bytes do not match ${artifactPath} at artifact Git commit ${normalizedCommit}`);

  const absoluteCatalogPath = path.resolve(catalogPath);
  let catalog;
  if (fs.existsSync(absoluteCatalogPath)) {
    catalog = validateCatalog(parseJsonBytes(fs.readFileSync(absoluteCatalogPath), absoluteCatalogPath));
  } else {
    catalog = { schemaVersion: SCHEMA_VERSION, latest: version, versions: {} };
  }
  const pointer = {
    repository: normalizedRepository,
    commit: normalizedCommit,
    path: artifactPath,
    sha256: sha256(manifestBytes),
  };
  const existing = catalog.versions[version];
  if (existing && stableJson(existing.manifest) !== stableJson(pointer)) {
    fail(`catalog version ${version} already points to a different release artifact`);
  }
  catalog.versions[version] = { manifest: pointer };
  validateCatalog(catalog);
  atomicWrite(absoluteCatalogPath, Buffer.from(catalogSerialization(catalog)));
  return catalog;
}

export function setCatalogLatest({ catalogPath, version }) {
  const absoluteCatalogPath = path.resolve(catalogPath);
  const catalog = validateCatalog(parseJsonBytes(fs.readFileSync(absoluteCatalogPath), absoluteCatalogPath));
  const normalizedVersion = parseVersion(version);
  if (!Object.hasOwn(catalog.versions, normalizedVersion)) fail(`catalog has no version ${normalizedVersion}`);
  catalog.latest = normalizedVersion;
  validateCatalog(catalog);
  atomicWrite(absoluteCatalogPath, Buffer.from(catalogSerialization(catalog)));
  return catalog;
}

function parseOptions(args, allowed) {
  const options = {};
  for (let index = 0; index < args.length; index += 1) {
    const key = args[index];
    if (!key.startsWith('--')) fail(`unexpected argument ${JSON.stringify(key)}`);
    if (!allowed.has(key)) fail(`unknown option ${key}`);
    if (Object.hasOwn(options, key)) fail(`duplicate option ${key}`);
    const value = args[index + 1];
    if (value === undefined || value.startsWith('--')) fail(`option ${key} needs a value`);
    options[key] = value;
    index += 1;
  }
  return options;
}

function required(options, name) {
  const value = options[name];
  if (value === undefined || value.length === 0) fail(`required option ${name} is missing`);
  return value;
}

export const HELP = `Usage:
  node scripts/docs/generate.mjs generate --source <git-ref> --repository <Owner/Repo> --version <semver> --out <directory> [--source-repo <checkout>] [--schema-version 1]
  node scripts/docs/generate.mjs preview --repository <Owner/Repo> --version <semver> --out <directory> [--root <public-dir> --source-commit <40-hex>] [--schema-version 1]
  node scripts/docs/generate.mjs catalog add --manifest <manifest.json> --repository <Owner/Repo> --artifact-commit <40-hex> --catalog <catalog.json> [--source-repo <checkout>] [--artifact-repo <checkout>]
  node scripts/docs/generate.mjs catalog set-latest --catalog <catalog.json> --version <semver>

Repository checkout options default to the current working directory. catalog add reads both selected commits locally and performs no network or publication operation.
generate reads only docs/public from the selected Git commit and writes manifest.json outside that source tree.
preview reads a filesystem directory, writes a manifest with preview: true, and cannot be added to a release catalog.
catalog add records the commit containing versions/<version>/manifest.json; that is separate from manifest.source.commit.
`;

function runCli(argv) {
  const [command, ...rest] = argv;
  if (command === '--help' || command === '-h' || command === undefined) {
    process.stdout.write(HELP);
    return;
  }
  if (command === 'generate') {
    const options = parseOptions(rest, new Set(['--source', '--repository', '--version', '--out', '--source-repo', '--schema-version']));
    const source = required(options, '--source');
    const repository = required(options, '--repository');
    const version = required(options, '--version');
    const outputDirectory = required(options, '--out');
    const schemaVersion = options['--schema-version'] ?? SCHEMA_VERSION;
    const root = findGitRoot(options['--source-repo'] ? path.resolve(options['--source-repo']) : process.cwd());
    const manifest = generateFromGit({ cwd: root, source, version, repository, schemaVersion });
    const result = writeManifest(manifest, outputDirectory, path.join(root, PUBLIC_ROOT));
    process.stdout.write(`Generated manifest for ${version} from ${manifest.source.commit}: ${result.outputFile}\nSHA-256: ${result.sha256}\n`);
    return;
  }
  if (command === 'preview') {
    const options = parseOptions(rest, new Set(['--repository', '--version', '--out', '--root', '--source-commit', '--schema-version']));
    const repository = required(options, '--repository');
    const version = required(options, '--version');
    const outputDirectory = required(options, '--out');
    const cwd = process.cwd();
    const root = findGitRoot(cwd);
    const publicRoot = options['--root'] ? path.resolve(options['--root']) : path.join(root, PUBLIC_ROOT);
    const sourceCommit = options['--source-commit'] ?? resolveGitCommit(root, 'HEAD');
    if (options['--root'] !== undefined && options['--source-commit'] === undefined) fail('--source-commit is required when --root is specified');
    const manifest = generatePreview({ root: publicRoot, version, repository, sourceCommit, schemaVersion: options['--schema-version'] ?? SCHEMA_VERSION });
    const result = writeManifest(manifest, outputDirectory, publicRoot);
    process.stdout.write(`PREVIEW ONLY (filesystem content; not release provenance): ${result.outputFile}\nSHA-256: ${result.sha256}\n`);
    return;
  }
  if (command === 'catalog') {
    const [action, ...catalogArgs] = rest;
    if (action === 'add') {
      const options = parseOptions(catalogArgs, new Set(['--manifest', '--repository', '--artifact-commit', '--catalog', '--source-repo', '--artifact-repo']));
      const catalog = addCatalogVersion({
        manifestPath: required(options, '--manifest'),
        repository: required(options, '--repository'),
        artifactCommit: required(options, '--artifact-commit'),
        catalogPath: required(options, '--catalog'),
        sourceCwd: options['--source-repo'] ? path.resolve(options['--source-repo']) : process.cwd(),
        artifactCwd: options['--artifact-repo'] ? path.resolve(options['--artifact-repo']) : process.cwd(),
      });
      process.stdout.write(`Added catalog version; latest remains ${catalog.latest}\n`);
      return;
    }
    if (action === 'set-latest') {
      const options = parseOptions(catalogArgs, new Set(['--catalog', '--version']));
      const catalog = setCatalogLatest({ catalogPath: required(options, '--catalog'), version: required(options, '--version') });
      process.stdout.write(`Catalog latest is now ${catalog.latest}\n`);
      return;
    }
    fail('catalog requires add or set-latest');
  }
  fail(`unknown command ${JSON.stringify(command)}\n\n${HELP}`);
}

const currentFile = fileURLToPath(import.meta.url);
if (process.argv[1] && path.resolve(process.argv[1]) === currentFile) {
  try {
    runCli(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`docs-manifest: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
