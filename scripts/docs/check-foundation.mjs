#!/usr/bin/env node
import { readFile, readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseFrontmatter } from './generate.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const publicRoot = path.join(root, 'docs/public');
const errors = [];
const statuses = new Set(['draft', 'needs-rewrite', 'ready']);
const workstreams = new Set([
  'start',
  'core',
  'browser',
  'discovery',
  'evidence',
  'recipes',
  'integration',
]);
const dispositions = new Set([
  'retain-design-history',
  'retain-draft-fixture',
  'consolidate-and-preserve-url',
]);
const isText = (value) => typeof value === 'string' && value.trim().length > 0;
const isRelative = (value) =>
  isText(value) && !path.isAbsolute(value) && !value.split(/[\\/]/).includes('..');
const check = (condition, message) => {
  if (!condition) errors.push(message);
};

async function exists(relative) {
  if (!isRelative(relative)) return false;
  try {
    return (await stat(path.join(root, relative))).isFile();
  } catch {
    return false;
  }
}

async function collect(directory, output = []) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.name.startsWith('_') || ['AGENTS.md', 'README.md'].includes(entry.name)) continue;
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) await collect(file, output);
    else if (/\.mdx?$/.test(entry.name)) output.push(path.relative(publicRoot, file));
  }
  return output;
}

function style(source, file) {
  check(!source.includes('\u2014'), file + ': em dash found');
  check(
    !/\b(?:python(?:3)?\s+-m\s+pip|pip(?:3)?\s+install|uv\s+pip)\b/.test(source),
    file + ': use uv project commands',
  );
}

try {
  const map = JSON.parse(
    await readFile(path.join(root, 'docs/documentation/page-map.json'), 'utf8'),
  );
  check(map.schemaVersion === 1 && map.release === '0.2.0', 'Invalid foundation version');
  if (!Array.isArray(map.pages) || !Array.isArray(map.legacy))
    throw new Error('Page and legacy inventories are required');
  const assigned = new Set();
  const destinations = new Set(map.pages.map((page) => page.file));
  let draftCount = 0;
  for (const page of map.pages) {
    check(
      isRelative(page.file) && page.file.endsWith('.md'),
      'Invalid Markdown destination: ' + page.file,
    );
    check(!assigned.has(page.file), 'Duplicate destination: ' + page.file);
    assigned.add(page.file);
    check(isText(page.title) && isText(page.goal), page.file + ': title and goal required');
    check(statuses.has(page.status), page.file + ': invalid status');
    check(workstreams.has(page.workstream), page.file + ': invalid workstream');
    check(
      Array.isArray(page.outline) && page.outline.length > 0 && page.outline.every(isText),
      page.file + ': outline required',
    );
    for (const key of ['sources', 'authority']) {
      check(Array.isArray(page[key]) && page[key].length > 0, page.file + ': ' + key + ' required');
      for (const file of page[key] || []) {
        const relative = key === 'sources' ? 'docs/public/' + file : file;
        check(await exists(relative), page.file + ': missing ' + key + ' file ' + file);
      }
    }
    if (!(await exists('docs/public/' + page.file))) {
      errors.push('Missing destination: ' + page.file);
      continue;
    }
    const source = await readFile(path.join(publicRoot, page.file), 'utf8');
    const { metadata } = parseFrontmatter(source, page.file);
    if (page.status === 'draft') {
      draftCount += 1;
      check(metadata.draft === true, page.file + ': skeleton must remain draft');
      check(
        metadata.title === page.title && metadata.description === page.goal,
        page.file + ': frontmatter differs from page map',
      );
      style(source, page.file);
      for (const heading of page.outline || [])
        check(
          source.includes('\n## ' + heading + '\n'),
          page.file + ': missing outline heading ' + heading,
        );
    }
    if (page.status === 'ready') {
      check(metadata.draft !== true, page.file + ': ready page still has draft frontmatter');
      check(await exists(page.reviewReceipt), page.file + ': ready page requires a review receipt');
      style(source, page.file);
      check(!/<!-- Authoring task:/.test(source), page.file + ': unfinished authoring task');
    }
  }
  for (const item of map.legacy) {
    check(!assigned.has(item.file), 'Duplicate legacy assignment: ' + item.file);
    assigned.add(item.file);
    check(await exists('docs/public/' + item.file), 'Missing legacy page: ' + item.file);
    check(dispositions.has(item.disposition), item.file + ': invalid legacy disposition');
    check(Array.isArray(item.destinations), item.file + ': destination list required');
    for (const destination of item.destinations || [])
      check(destinations.has(destination), item.file + ': unknown replacement ' + destination);
    if (item.disposition === 'consolidate-and-preserve-url')
      check(item.destinations.length > 0, item.file + ': replacement destination required');
  }
  for (const file of await collect(publicRoot)) {
    if (file.startsWith('releases/') || file.startsWith('python-api/') || file.startsWith('api/'))
      continue;
    check(assigned.has(file), 'Unassigned learning page: ' + file);
    const source = await readFile(path.join(publicRoot, file), 'utf8');
    check(
      !/\b(?:python(?:3)?\s+-m\s+pip|pip(?:3)?\s+install|uv\s+pip)\b/.test(source),
      file + ': use uv project commands',
    );
  }
  for (const file of [
    'docs/public/AGENTS.md',
    'docs/documentation/README.md',
    'docs/documentation/roadmap.md',
    'docs/documentation/worker-brief.md',
    'docs/documentation/review-receipt.md',
    'docs/documentation/page-template.md',
  ])
    style(await readFile(path.join(root, file), 'utf8'), file);
  if (errors.length) throw new Error(errors.join('\n'));
  console.log(
    'Foundation checked: ' +
      map.pages.length +
      ' destination pages, ' +
      draftCount +
      ' drafts, ' +
      map.legacy.length +
      ' legacy dispositions. No example execution or browser proof claimed.',
  );
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
