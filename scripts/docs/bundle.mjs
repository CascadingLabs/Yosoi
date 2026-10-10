import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { generatePreview, validateManifest } from './generate.mjs';
import { copyPublicTree, authoredPages, readPublicNavigation } from './content.mjs';
import { resolveNavigation } from './navigation.mjs';
import * as jsonc from 'jsonc-parser';
import { verifyReference } from './reference/generate.mjs';

const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const git = (...args) => execFileSync('git', args);
const json = (value) => JSON.stringify(value, null, 2) + '\n';
const contracts = [
  'generate.mjs',
  'content.mjs',
  'navigation.mjs',
  'reference/generate.mjs',
  'reference/model.mjs',
  'reference/sdk-discovery.mjs',
  'reference/toolchain.json',
  'reference/sdk-policy.json',
];

export async function createBundle({ source, version, reference, out }) {
  if (!/^[a-f0-9]{40}$/.test(source)) throw new Error('A full source commit is required');
  if (git('rev-parse', 'HEAD').toString().trim() !== source)
    throw new Error('Bundle tooling must run from the selected source checkout');
  const api = verifyReference(reference);
  if (
    api.source.commit !== source ||
    api.source.repository !== 'CascadingLabs/Yosoi' ||
    api.version !== version
  )
    throw new Error('Reference must match the bundle source, repository, and version');
  await mkdir(out); // Never replace an existing snapshot.
  const temp = await mkdtemp(path.join(os.tmpdir(), 'yosoi-docs-'));
  let manifest, navigation;
  try {
    const archive = path.join(temp, 'public.tar');
    git('archive', `--output=${archive}`, source, 'docs/public');
    execFileSync('tar', ['-xf', archive, '-C', temp]);
    navigation = await readPublicNavigation(path.join(temp, 'docs/public'), jsonc);
    await mkdir(path.join(out, 'docs/public'), { recursive: true });
    await copyPublicTree(path.join(temp, 'docs/public'), path.join(out, 'docs/public'));
    manifest = generatePreview({
      root: path.join(out, 'docs/public'),
      version,
      repository: 'CascadingLabs/Yosoi',
      sourceCommit: source,
    });
    delete manifest.preview;
    validateManifest(manifest, { allowPreview: false });
    const publicFiles = new Set([
      ...Object.values(manifest.pages).map((page) => page.file),
      ...Object.keys(manifest.assets),
    ]);
    const prune = async (dir, prefix = '') => {
      for (const entry of await readdir(dir, { withFileTypes: true })) {
        const file = prefix + entry.name;
        if (entry.isDirectory()) await prune(path.join(dir, entry.name), file + '/');
        else if (!publicFiles.has(file)) await rm(path.join(dir, entry.name));
      }
    };
    await prune(path.join(out, 'docs/public'));
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
  const writeBlob = async (file, destination) => {
    const bytes = git('show', `${source}:${file}`);
    await mkdir(path.dirname(path.join(out, destination)), { recursive: true });
    await writeFile(path.join(out, destination), bytes);
  };
  for (const page of Object.values(manifest.pages)) {
    if (page.format !== 'markdown')
      throw new Error('Published bundles currently support Markdown only');
  }
  const navigationFile = git('ls-tree', '--name-only', source, '--', 'docs/public/_navigation.json')
    .toString()
    .trim();
  if (navigationFile) await writeBlob(navigationFile, navigationFile);
  for (const file of contracts) await writeBlob(`scripts/docs/${file}`, `scripts/docs/${file}`);
  await cp(reference, path.join(out, 'reference'), { recursive: true });
  await writeFile(path.join(out, 'manifest.json'), json(manifest));
  const pages = authoredPages(manifest);
  const referencePages = [];
  for (const [slug, item] of Object.entries(api.pages)) {
    const page = JSON.parse(await readFile(path.join(reference, 'en', item.file), 'utf8'));
    referencePages.push({
      route: slug === 'index' ? 'api' : `api/${slug}`,
      id: slug === 'index' ? 'api' : `api/${slug}`,
      title: page.publicPath.split('::').at(-1),
      file: `reference/en/${item.file}`,
      format: 'rust-api',
      sha256: item.localeHashes.en,
      kind: page.kind,
      publicPath: page.publicPath,
      order: 1000,
    });
  }
  const inventory = [...pages, ...referencePages];
  const archiveManifest = {
    schemaVersion: 1,
    version,
    tag: `v${version}`,
    sourceCommit: source,
    navigation: resolveNavigation(
      inventory,
      navigation.metadata || {
        schemaVersion: 1,
        sections: [
          { title: 'Docs', pages: pages.map((page) => page.file) },
          { title: 'Reference', generated: 'rust-api' },
        ],
      },
    ),
    pages: [
      ...pages.map((page) => ({ ...page, file: `docs/public/${page.file}`, format: 'markdown' })),
      ...referencePages,
    ],
    assets: Object.fromEntries(
      Object.entries(manifest.assets).map(([file, item]) => [
        file,
        { file: `docs/public/${file}`, sha256: item.sha256 },
      ]),
    ),
    reference: { sdk: api.sdk },
  };
  await writeFile(path.join(out, 'archive-manifest.json'), json(archiveManifest));
  const files = {};
  const walk = async (directory, prefix = '') => {
    for (const entry of (await readdir(directory, { withFileTypes: true })).sort((a, b) =>
      a.name.localeCompare(b.name),
    )) {
      const file = prefix + entry.name;
      if (entry.isDirectory()) await walk(path.join(directory, entry.name), file + '/');
      else if (entry.isFile())
        files[file] = sha256(await readFile(path.join(directory, entry.name)));
      else throw new Error('Bundles may contain only regular files and directories');
    }
  };
  await walk(out);
  const bundle = {
    schemaVersion: 1,
    version,
    sourceCommit: source,
    repository: 'CascadingLabs/Yosoi',
    files,
  };
  await writeFile(path.join(out, 'bundle.json'), json(bundle));
  return bundle;
}

export async function registerBundle({
  checkout,
  bundle,
  source,
  version,
  sourceCheckout = process.cwd(),
}) {
  if (!/^[a-f0-9]{40}$/.test(source)) throw new Error('A full source commit is required');
  const artifactCommit = execFileSync('git', ['-C', checkout, 'rev-parse', 'HEAD'], {
    encoding: 'utf8',
  }).trim();
  const bundlePath = `snapshots/${source}/bundle.tar.gz`;
  const bytes = execFileSync('git', ['-C', checkout, 'show', `${artifactCommit}:${bundlePath}`], {
    maxBuffer: 128 * 1024 * 1024,
  });
  if (sha256(bytes) !== sha256(await readFile(bundle)))
    throw new Error('Committed bundle differs from publication input');
  const file = path.join(checkout, 'catalog.json');
  let catalog;
  try {
    catalog = JSON.parse(await readFile(file, 'utf8'));
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    catalog = { schemaVersion: 1, latest: null, snapshots: {} };
  }
  if (catalog.schemaVersion !== 1 || !catalog.snapshots)
    throw new Error('Unsupported docs bundle catalog');
  const existing = catalog.snapshots[source];
  if (existing && (existing.sha256 !== sha256(bytes) || existing.version !== version))
    throw new Error('Published docs snapshots are immutable');
  const manifestPath = `snapshots/${source}/content/archive-manifest.json`;
  const archiveBytes = execFileSync('git', [
    '-C',
    checkout,
    'show',
    `${artifactCommit}:${manifestPath}`,
  ]);
  const archive = JSON.parse(archiveBytes);
  if (archive.schemaVersion !== 1 || archive.sourceCommit !== source || archive.version !== version)
    throw new Error('Committed archive manifest differs from publication identity');
  catalog.snapshots[source] = existing || {
    sourceCommit: source,
    version,
    repository: 'CascadingLabs/Yosoi',
    artifactCommit,
    bundlePath,
    sha256: sha256(bytes),
    manifestPath,
    manifestSha256: sha256(archiveBytes),
  };
  // Serialize publications and never promote an older main ancestor on a retry.
  let promote = true;
  if (catalog.latest && catalog.latest !== source) {
    const descendant = execFileSync(
      'git',
      ['-C', sourceCheckout, 'merge-base', catalog.latest, source],
      {
        encoding: 'utf8',
      },
    ).trim();
    if (descendant !== catalog.latest && descendant !== source)
      throw new Error('Docs publication diverges from latest');
    if (descendant === source) promote = false;
  }
  if (promote) catalog.latest = source;
  await writeFile(file, json(catalog));
  return catalog;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [command, ...args] = process.argv.slice(2);
  const { values } = parseArgs({
    args,
    options: Object.fromEntries(
      ['source', 'version', 'reference', 'out', 'checkout', 'bundle'].map((key) => [
        key,
        { type: 'string' },
      ]),
    ),
  });
  if (command === 'create') await createBundle(values);
  else if (command === 'register') await registerBundle(values);
  else throw new Error('Use create or register');
}
