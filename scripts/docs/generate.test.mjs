import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { test } from 'node:test';

import {
  addCatalogVersion,
  generateFromGit,
  generatePreview,
  parseFrontmatter,
  setCatalogLatest,
  validateManifest,
  writeManifest,
} from './generate.mjs';

function git(root, ...args) {
  return execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

function writeFiles(root, files) {
  for (const [relativePath, content] of Object.entries(files)) {
    const target = path.join(root, relativePath);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content);
  }
}

function makeGitRepo(files, symlinks = []) {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'docs-manifest-test-'));
  const root = path.join(parent, 'repo');
  fs.mkdirSync(root);
  git(root, 'init', '-q');
  git(root, 'config', 'user.name', 'Manifest Test');
  git(root, 'config', 'user.email', 'manifest-test@example.invalid');
  git(root, 'config', 'commit.gpgsign', 'false');
  writeFiles(root, files);
  for (const [relativePath, target] of symlinks) {
    const symlinkPath = path.join(root, relativePath);
    fs.mkdirSync(path.dirname(symlinkPath), { recursive: true });
    fs.symlinkSync(target, symlinkPath);
  }
  git(root, 'add', '-A');
  git(root, 'commit', '-qm', 'test docs snapshot');
  return { parent, root, commit: git(root, 'rev-parse', 'HEAD') };
}

function baseFiles(extra = {}) {
  return {
    'docs/public/index.md': '---\ntitle: Home\ndescription: "Overview: tools and ideas"\norder: 0\n---\n# Welcome\n',
    'docs/public/releases/index.md': '---\ntitle: Release notes\ndescription: User-facing changes for published releases\norder: 0\n---\n# Release notes\n',
    'docs/public/releases/0-2-0.md': '---\ntitle: Yosoi 0.2.0\nversion: 0.2.0\ndate: 2026-10-04\nchannel: recommended\nprevious: 0.1.0\n---\n# Yosoi 0.2.0\n',
    'docs/public/releases/0-3-0.md': '---\ntitle: Yosoi 0.3.0\nversion: 0.3.0\ndate: 2026-11-04\nchannel: preview\ndraft: true\n---\n# Draft release\n',
    'docs/public/guides/locating.md': '---\ntitle: Locating\norder: 3\n---\n# Locate\n',
    'docs/public/concepts/index.md': '---\ntitle: Concepts\n---\n# Concepts\n',
    'docs/public/components.mdx': '---\ntitle: Components\n---\n# Components\n\n<Callout title="Demo fixture">\nThis is Markdown inside the supported wrapper.\n</Callout>\n',
    'docs/public/assets/demo.svg': '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n',
    'docs/public/README.md': '# Private readme\n',
    'docs/public/AGENTS.md': '# Local instructions\n',
    'docs/public/_private/ignored.md': '# Excluded\n',
    'docs/public/draft.mdx': '---\ndraft: true\n---\n{this would be executable if included}\n',
    ...extra,
  };
}

test('builds a deterministic manifest from one Git snapshot and applies the public allowlist', (context) => {
  const { parent, root, commit } = makeGitRepo(baseFiles());
  context.after(() => fs.rmSync(parent, { recursive: true, force: true }));
  const input = { cwd: root, source: commit, repository: 'Owner/Repo', version: '0.0.1' };

  const first = generateFromGit(input);
  const second = generateFromGit(input);

  assert.deepEqual(first, second);
  assert.deepEqual(Object.keys(first.pages), ['/', '/components', '/concepts', '/guides/locating', '/releases', '/releases/0-2-0']);
  assert.equal(first.pages['/'].title, 'Home');
  assert.equal(first.pages['/'].description, 'Overview: tools and ideas');
  assert.equal(first.pages['/concepts'].file, 'concepts/index.md');
  assert.equal(first.pages['/components'].format, 'mdx');
  assert.equal(first.pages['/guides/locating'].order, 3);
  assert.deepEqual(
    Object.fromEntries(['version', 'date', 'channel', 'previous'].map((field) => [field, first.pages['/releases/0-2-0'][field]])),
    { version: '0.2.0', date: '2026-10-04', channel: 'recommended', previous: '0.1.0' },
  );
  assert.equal(Object.hasOwn(first.pages, '/draft'), false);
  assert.equal(Object.hasOwn(first.pages, '/releases/0-3-0'), false);
  assert.equal(Object.hasOwn(first.pages, '/readme'), false);
  assert.equal(Object.hasOwn(first.pages, '/agents'), false);
  assert.deepEqual(Object.keys(first.assets), ['assets/demo.svg']);
  assert.equal(first.pages['/'].sha256, crypto.createHash('sha256').update(baseFiles()['docs/public/index.md']).digest('hex'));
  assert.equal(first.source.commit, commit);
  assert.equal(first.source.root, 'docs/public');
  assert.throws(() => generateFromGit({ ...input, schemaVersion: 2 }), /unsupported schema version/);
  const badReleaseMetadata = structuredClone(first);
  badReleaseMetadata.pages['/releases/0-2-0'].channel = false;
  assert.throws(() => validateManifest(badReleaseMetadata), /channel must be a non-empty string/);
  const unknownReleaseMetadata = structuredClone(first);
  unknownReleaseMetadata.pages['/releases/0-2-0'].audience = 'users';
  assert.throws(() => validateManifest(unknownReleaseMetadata), /contains unsupported fields/);
  const releaseMetadataOnGuide = structuredClone(first);
  releaseMetadataOnGuide.pages['/guides/locating'].version = '0.2.0';
  assert.throws(() => validateManifest(releaseMetadataOnGuide), /release metadata is only allowed under releases\//);

  fs.writeFileSync(path.join(root, 'docs/public/index.md'), '# Dirty working copy\n');
  fs.writeFileSync(path.join(root, 'docs/public/uncommitted.md'), '# Uncommitted\n');
  assert.deepEqual(generateFromGit(input), first, 'Git mode reads the selected commit, not working-tree content');
});

test('requires a root index for the generated website entry point', (context) => {
  const { parent, root, commit } = makeGitRepo({ 'docs/public/guide.md': '# Guide\n' });
  context.after(() => fs.rmSync(parent, { recursive: true, force: true }));
  assert.throws(() => generateFromGit({ cwd: root, source: commit, repository: 'Owner/Repo', version: '0.0.1' }), /root index/);
});

test('rejects route collisions, unsafe paths, symbolic links, and executable MDX', (context) => {
  const collision = makeGitRepo(baseFiles({
    'docs/public/guides.md': '# One\n',
    'docs/public/guides/index.md': '# Two\n',
  }));
  const symlink = makeGitRepo(baseFiles(), [['docs/public/assets/linked.svg', 'demo.svg']]);
  const executableMdx = makeGitRepo(baseFiles({
    'docs/public/unsafe.mdx': '---\ntitle: Unsafe\n---\n{globalThis.process.exit()}\n',
  }));
  const invalidRoute = makeGitRepo(baseFiles({
    'docs/public/Bad Name.md': '# Invalid route source\n',
  }));
  const uppercaseIndex = makeGitRepo(baseFiles({
    'docs/public/Index.md': '# Invalid index case\n',
  }));
  const uppercaseExtension = makeGitRepo(baseFiles({
    'docs/public/upper.MD': '# Invalid extension case\n',
  }));
  context.after(() => {
    fs.rmSync(collision.parent, { recursive: true, force: true });
    fs.rmSync(symlink.parent, { recursive: true, force: true });
    fs.rmSync(executableMdx.parent, { recursive: true, force: true });
    fs.rmSync(invalidRoute.parent, { recursive: true, force: true });
    fs.rmSync(uppercaseIndex.parent, { recursive: true, force: true });
    fs.rmSync(uppercaseExtension.parent, { recursive: true, force: true });
  });

  assert.throws(() => generateFromGit({ cwd: collision.root, source: collision.commit, repository: 'Owner/Repo', version: '0.0.1' }), /route collision/);
  assert.throws(() => generateFromGit({ cwd: symlink.root, source: symlink.commit, repository: 'Owner/Repo', version: '0.0.1' }), /symbolic links/);
  assert.throws(() => generateFromGit({ cwd: executableMdx.root, source: executableMdx.commit, repository: 'Owner/Repo', version: '0.0.1' }), /MDX expressions/);
  assert.throws(() => generateFromGit({ cwd: invalidRoute.root, source: invalidRoute.commit, repository: 'Owner/Repo', version: '0.0.1' }), /lowercase kebab case/);
  assert.throws(() => generateFromGit({ cwd: uppercaseIndex.root, source: uppercaseIndex.commit, repository: 'Owner/Repo', version: '0.0.1' }), /lowercase kebab case/);
  assert.throws(() => generateFromGit({ cwd: uppercaseExtension.root, source: uppercaseExtension.commit, repository: 'Owner/Repo', version: '0.0.1' }), /extensions must be lowercase/);
});

test('parses quoted colon scalars and makes filesystem previews ineligible for release catalogs', (context) => {
  const frontmatter = parseFrontmatter('---\ntitle: "A title: with a colon"\ndescription: \'It\'\'s useful: yes\'\nversion: 0.2.0\ndate: 2026-10-04\nchannel: recommended\nprevious: \'0.1.0\'\norder: 4\ndraft: false\n---\n# Heading\n');
  assert.deepEqual(frontmatter.metadata, {
    title: 'A title: with a colon',
    description: "It's useful: yes",
    version: '0.2.0',
    date: '2026-10-04',
    channel: 'recommended',
    previous: '0.1.0',
    order: 4,
    draft: false,
  });
  assert.throws(() => parseFrontmatter('---\nunknown: value\n---\n'), /unsupported or malformed frontmatter field/);
  assert.throws(() => parseFrontmatter('---\nversion:\n---\n'), /frontmatter version must be a non-empty string/);
  assert.throws(() => parseFrontmatter('---\ndate: [2026-10-04]\n---\n'), /unsupported YAML syntax/);
  assert.throws(
    () => parseFrontmatter('---\nversion: 0.2.0\n---\n', 'guides/locating.md'),
    /release metadata is only allowed under releases\//,
  );

  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'docs-manifest-preview-'));
  const publicRoot = path.join(parent, 'docs', 'public');
  const manifestPath = path.join(parent, 'manifest.json');
  fs.mkdirSync(publicRoot, { recursive: true });
  fs.writeFileSync(path.join(publicRoot, 'index.md'), '---\ntitle: Preview\n---\n# Preview\n');
  context.after(() => fs.rmSync(parent, { recursive: true, force: true }));

  const preview = generatePreview({ root: publicRoot, version: '0.0.1', repository: 'Owner/Repo', sourceCommit: 'a'.repeat(40) });
  assert.equal(preview.preview, true);
  assert.equal(preview.source.commit, 'a'.repeat(40));
  assert.equal(validateManifest(preview).preview, true);
  fs.writeFileSync(manifestPath, `${JSON.stringify(preview, null, 2)}\n`);
  assert.throws(() => addCatalogVersion({
    catalogPath: path.join(parent, 'catalog.json'),
    manifestPath,
    repository: 'Owner/Archive',
    artifactCommit: 'b'.repeat(40),
  }), /preview manifests cannot be added/);
  assert.throws(() => writeManifest(preview, path.join(publicRoot, 'generated'), publicRoot), /outside the selected source root/);
});

test('keeps release manifests immutable by source identity', (context) => {
  const { parent, root, commit } = makeGitRepo(baseFiles());
  const manifest = generateFromGit({ cwd: root, source: commit, repository: 'Owner/Repo', version: '0.0.1' });
  const outputDirectory = path.join(parent, 'release-artifacts');
  context.after(() => fs.rmSync(parent, { recursive: true, force: true }));

  assert.equal(writeManifest(manifest, outputDirectory, path.join(root, 'docs', 'public')).changed, true);
  assert.equal(writeManifest(manifest, outputDirectory, path.join(root, 'docs', 'public')).changed, false);
  assert.throws(() => writeManifest({ ...manifest, source: { ...manifest.source, commit: 'f'.repeat(40) } }, outputDirectory, path.join(root, 'docs', 'public')), /conflicting release identity/);
});

test('catalog pointers hash the manifest artifact and latest is an explicit alias', (context) => {
  const source = makeGitRepo(baseFiles());
  const { parent: artifactParent, root: artifactRoot, commit: missingArtifactCommit } = makeGitRepo({ 'README.md': 'artifact repository\n' });
  const manifest = generateFromGit({ cwd: source.root, source: source.commit, repository: 'Owner/Repo', version: '0.0.1' });
  const manifestPath = path.join(artifactRoot, 'versions', '0.0.1', 'manifest.json');
  const catalogPath = path.join(artifactParent, 'catalog.json');
  const manifestBytes = Buffer.from(`${JSON.stringify(manifest, null, 2)}\n`);
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
  fs.writeFileSync(manifestPath, 'wrong bytes\n');
  git(artifactRoot, 'add', '-A');
  git(artifactRoot, 'commit', '-qm', 'store wrong docs manifest');
  const wrongArtifactCommit = git(artifactRoot, 'rev-parse', 'HEAD');
  fs.writeFileSync(manifestPath, manifestBytes);
  git(artifactRoot, 'add', '-A');
  git(artifactRoot, 'commit', '-qm', 'store docs manifest');
  const artifactCommit = git(artifactRoot, 'rev-parse', 'HEAD');
  context.after(() => {
    fs.rmSync(source.parent, { recursive: true, force: true });
    fs.rmSync(artifactParent, { recursive: true, force: true });
  });

  assert.throws(() => addCatalogVersion({
    catalogPath,
    manifestPath,
    repository: 'Owner/Archive',
    artifactCommit: wrongArtifactCommit,
    sourceCwd: source.root,
    artifactCwd: artifactRoot,
  }), /do not match/);
  assert.throws(() => addCatalogVersion({
    catalogPath,
    manifestPath,
    repository: 'Owner/Archive',
    artifactCommit: missingArtifactCommit,
    sourceCwd: source.root,
    artifactCwd: artifactRoot,
  }), /does not contain/);

  const catalog = addCatalogVersion({ catalogPath, manifestPath, repository: 'Owner/Archive', artifactCommit, sourceCwd: source.root, artifactCwd: artifactRoot });
  assert.equal(catalog.latest, '0.0.1');
  assert.deepEqual(catalog.versions['0.0.1'].manifest, {
    repository: 'Owner/Archive',
    commit: artifactCommit,
    path: 'versions/0.0.1/manifest.json',
    sha256: crypto.createHash('sha256').update(manifestBytes).digest('hex'),
  });
  const originalCatalogBytes = fs.readFileSync(catalogPath);
  const catalogWithQueryPath = JSON.parse(originalCatalogBytes);
  catalogWithQueryPath.versions['0.0.1'].manifest.path += '?raw';
  fs.writeFileSync(catalogPath, JSON.stringify(catalogWithQueryPath));
  assert.throws(() => addCatalogVersion({ catalogPath, manifestPath, repository: 'Owner/Archive', artifactCommit, sourceCwd: source.root, artifactCwd: artifactRoot }), /invalid artifact path/);
  const catalogWithExtraField = JSON.parse(originalCatalogBytes);
  catalogWithExtraField.versions['0.0.1'].manifest.extra = true;
  fs.writeFileSync(catalogPath, JSON.stringify(catalogWithExtraField));
  assert.throws(() => addCatalogVersion({ catalogPath, manifestPath, repository: 'Owner/Archive', artifactCommit, sourceCwd: source.root, artifactCwd: artifactRoot }), /unsupported fields/);
  fs.writeFileSync(catalogPath, originalCatalogBytes);
  git(artifactRoot, 'commit', '--allow-empty', '-qm', 'alternate artifact commit');
  const alternateArtifactCommit = git(artifactRoot, 'rev-parse', 'HEAD');
  assert.throws(() => addCatalogVersion({
    catalogPath,
    manifestPath,
    repository: 'Owner/Archive',
    artifactCommit: alternateArtifactCommit,
    sourceCwd: source.root,
    artifactCwd: artifactRoot,
  }), /different release artifact/);

  const nextManifest = generateFromGit({ cwd: source.root, source: source.commit, repository: 'Owner/Repo', version: '0.0.2' });
  const nextManifestPath = path.join(artifactRoot, 'versions', '0.0.2', 'manifest.json');
  fs.mkdirSync(path.dirname(nextManifestPath), { recursive: true });
  fs.writeFileSync(nextManifestPath, `${JSON.stringify(nextManifest, null, 2)}\n`);
  git(artifactRoot, 'add', '-A');
  git(artifactRoot, 'commit', '-qm', 'store next docs manifest');
  const nextArtifactCommit = git(artifactRoot, 'rev-parse', 'HEAD');
  assert.equal(addCatalogVersion({
    catalogPath,
    manifestPath: nextManifestPath,
    repository: 'Owner/Archive',
    artifactCommit: nextArtifactCommit,
    sourceCwd: source.root,
    artifactCwd: artifactRoot,
  }).latest, '0.0.1');
  assert.equal(setCatalogLatest({ catalogPath, version: '0.0.2' }).latest, '0.0.2');
});

test('catalog add rejects a preview manifest whose marker was removed', (context) => {
  const source = makeGitRepo(baseFiles());
  const publicRoot = path.join(source.root, 'docs', 'public');
  fs.writeFileSync(path.join(publicRoot, 'index.md'), '# Dirty working copy\n');
  const preview = generatePreview({ root: publicRoot, version: '0.0.1', repository: 'Owner/Repo', sourceCommit: source.commit });
  const forged = { ...preview };
  delete forged.preview;
  const artifact = makeGitRepo({
    'versions/0.0.1/manifest.json': `${JSON.stringify(forged, null, 2)}\n`,
  });
  const catalogPath = path.join(artifact.parent, 'catalog.json');
  context.after(() => {
    fs.rmSync(source.parent, { recursive: true, force: true });
    fs.rmSync(artifact.parent, { recursive: true, force: true });
  });

  assert.throws(() => addCatalogVersion({
    catalogPath,
    manifestPath: path.join(artifact.root, 'versions', '0.0.1', 'manifest.json'),
    repository: 'Owner/Archive',
    artifactCommit: artifact.commit,
    sourceCwd: source.root,
    artifactCwd: artifact.root,
  }), /does not match the selected source Git commit/);
});
