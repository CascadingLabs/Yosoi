import { expect, test } from 'vite-plus/test';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { registerBundle } from './bundle.mjs';

const scripts = fileURLToPath(new URL('./', import.meta.url));
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
const json = (value) => JSON.stringify(value, null, 2) + '\n';
test('publication binds public content, navigation, and API to one source and refuses preview identity drift', async () => {
  const work = fileURLToPath(new URL('../../.generated/docs-tests/', import.meta.url));
  await mkdir(work, { recursive: true });
  const fixture = await mkdtemp(path.join(work, 'bundle-'));
  const git = (...args) =>
    execFileSync(
      'git',
      [
        '-c',
        'user.name=Fixture',
        '-c',
        'user.email=fixture@example.invalid',
        '-c',
        'commit.gpgsign=false',
        '-c',
        'core.hooksPath=/dev/null',
        ...args,
      ],
      { cwd: fixture, encoding: 'utf8' },
    ).trim();
  try {
    await mkdir(path.join(fixture, 'docs/public'), { recursive: true });
    await writeFile(
      path.join(fixture, 'docs/public/index.md'),
      '---\ntitle: Overview\n---\n# Overview\nHello\n',
    );
    await writeFile(path.join(fixture, 'docs/public/AGENTS.md'), 'Private instructions');
    await writeFile(path.join(fixture, 'docs/public/draft.md'), '---\ndraft: true\n---\n# Draft\n');
    await writeFile(
      path.join(fixture, 'docs/public/_navigation.json'),
      json({
        schemaVersion: 1,
        sections: [
          { title: 'Start', pages: ['index.md'] },
          { title: 'Reference', generated: 'rust-api' },
        ],
      }),
    );
    await mkdir(path.join(fixture, 'scripts/docs'), { recursive: true });
    for (const file of [
      'generate.mjs',
      'content.mjs',
      'navigation.mjs',
      'reference/generate.mjs',
      'reference/model.mjs',
      'reference/sdk-discovery.mjs',
      'reference/toolchain.json',
      'reference/sdk-policy.json',
    ]) {
      await mkdir(path.dirname(path.join(fixture, 'scripts/docs', file)), { recursive: true });
      await cp(path.join(scripts, file), path.join(fixture, 'scripts/docs', file));
    }
    git('init', '-q');
    git('add', '.');
    git('commit', '-qm', 'Source');
    const source = git('rev-parse', 'HEAD');
    const reference = path.join(fixture, 'reference');
    await mkdir(path.join(reference, 'en/pages'), { recursive: true });
    const page = json({ publicPath: 'yosoi', kind: 'module', docs: 'SDK overview' });
    await writeFile(path.join(reference, 'en/pages/index.json'), page);
    const base = {
      schemaVersion: 1,
      kind: 'rust-api-reference',
      version: '0.1.0',
      source: { commit: source, repository: 'CascadingLabs/Yosoi' },
      sdk: { crate: 'yosoi', version: '0.1.0' },
      locales: ['en'],
      pages: { index: { file: 'pages/index.json', localeHashes: { en: hash(page) } } },
    };
    const provenance = json({ sourceCommit: source, contentDigest: hash(json(base)) });
    await writeFile(path.join(reference, 'provenance.json'), provenance);
    await writeFile(
      path.join(reference, 'manifest.json'),
      json({
        ...base,
        provenance: {
          file: 'provenance.json',
          sha256: hash(provenance),
          status: 'unsigned-preview',
        },
      }),
    );
    const out = path.join(fixture, 'output');
    const args = [
      path.join(scripts, 'bundle.mjs'),
      'create',
      '--source',
      source,
      '--version',
      '0.1.0',
      '--reference',
      reference,
      '--out',
      out,
    ];
    execFileSync('node', args, { cwd: fixture });
    const bundle = JSON.parse(await readFile(path.join(out, 'bundle.json'), 'utf8'));
    expect(bundle.sourceCommit).toBe(source);
    expect(bundle.files['docs/public/_navigation.json']).toBeTruthy();
    expect(bundle.files['docs/public/draft.md']).toBeUndefined();
    expect(bundle.files['docs/public/AGENTS.md']).toBeUndefined();
    const archive = JSON.parse(await readFile(path.join(out, 'archive-manifest.json'), 'utf8'));
    expect(archive.pages.map((item) => item.format)).toEqual(['markdown', 'rust-api']);
    expect(archive.navigation.children.map((item) => item.title)).toEqual(['Start', 'Reference']);
    expect(() =>
      execFileSync(
        'node',
        [...args.slice(0, -1), path.join(fixture, 'other'), '--version', '0.2.0'],
        { cwd: fixture, stdio: 'pipe' },
      ),
    ).toThrow();
  } finally {
    await rm(fixture, { recursive: true, force: true });
  }
});

test('catalog publication preserves immutable pointers and an older retry cannot replace latest', async () => {
  const work = fileURLToPath(new URL('../../.generated/docs-tests/', import.meta.url));
  await mkdir(work, { recursive: true });
  const fixture = await mkdtemp(path.join(work, 'catalog-'));
  const git = (repo, ...args) =>
    execFileSync(
      'git',
      [
        '-C',
        repo,
        '-c',
        'user.name=Fixture',
        '-c',
        'user.email=fixture@example.invalid',
        '-c',
        'commit.gpgsign=false',
        '-c',
        'core.hooksPath=/dev/null',
        ...args,
      ],
      { encoding: 'utf8' },
    ).trim();
  try {
    const sourceRepo = path.join(fixture, 'source');
    const artifacts = path.join(fixture, 'artifacts');
    await mkdir(sourceRepo);
    await mkdir(artifacts);
    git(sourceRepo, 'init', '-q');
    git(artifacts, 'init', '-q');
    await writeFile(path.join(sourceRepo, 'source'), 'old');
    git(sourceRepo, 'add', '.');
    git(sourceRepo, 'commit', '-qm', 'Old source');
    const old = git(sourceRepo, 'rev-parse', 'HEAD');
    await writeFile(path.join(sourceRepo, 'source'), 'new');
    git(sourceRepo, 'add', '.');
    git(sourceRepo, 'commit', '-qm', 'New source');
    const latest = git(sourceRepo, 'rev-parse', 'HEAD');
    for (const source of [latest, old]) {
      const dir = path.join(artifacts, 'snapshots', source);
      await mkdir(path.join(dir, 'content'), { recursive: true });
      await writeFile(path.join(dir, 'bundle.tar.gz'), source);
      await writeFile(
        path.join(dir, 'content/archive-manifest.json'),
        json({ schemaVersion: 1, version: '0.1.0', sourceCommit: source }),
      );
      git(artifacts, 'add', '.');
      git(artifacts, 'commit', '-qm', 'Immutable files');
      await registerBundle({
        checkout: artifacts,
        bundle: path.join(dir, 'bundle.tar.gz'),
        source,
        version: '0.1.0',
        sourceCheckout: sourceRepo,
      });
      git(artifacts, 'add', '.');
      git(artifacts, 'commit', '-qm', 'Catalog');
    }
    const catalog = JSON.parse(await readFile(path.join(artifacts, 'catalog.json'), 'utf8'));
    expect(catalog.latest).toBe(latest);
    expect(Object.keys(catalog.snapshots)).toHaveLength(2);
    const dir = path.join(artifacts, 'snapshots', latest);
    const originalPointer = catalog.snapshots[latest];
    await registerBundle({
      checkout: artifacts,
      bundle: path.join(dir, 'bundle.tar.gz'),
      source: latest,
      version: '0.1.0',
      sourceCheckout: sourceRepo,
    });
    const retry = JSON.parse(await readFile(path.join(artifacts, 'catalog.json'), 'utf8'));
    expect(retry.snapshots[latest]).toEqual(originalPointer);
    await expect(
      registerBundle({
        checkout: artifacts,
        bundle: path.join(dir, 'bundle.tar.gz'),
        source: latest,
        version: '0.2.0',
        sourceCheckout: sourceRepo,
      }),
    ).rejects.toThrow(/immutable/);
  } finally {
    await rm(fixture, { recursive: true, force: true });
  }
});
