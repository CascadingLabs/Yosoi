import assert from 'node:assert/strict';
import { test } from 'vite-plus/test';
import { parseNavigationMetadata as decode, resolveNavigation } from './navigation.mjs';
import * as jsonc from 'jsonc-parser';
const parseNavigationMetadata = (source) => decode(source, jsonc);
const page = (file, route, title, order = 0) => ({
  file,
  route,
  title,
  id: route || 'index',
  order,
});
const pages = [
  page('index.md', '', 'Yosoi'),
  page('quickstart.md', 'quickstart', 'Quick start'),
  page('cli/index.md', 'cli', 'CLI', 3),
  page('cli/map.md', 'cli/map', 'Map', 1),
  page('cli/search.md', 'cli/search', 'Search', 2),
  page('api/index.md', 'api', 'Reference', 1000),
  page('api/sdk/struct/document.md', 'api/sdk/struct/document', 'Document', 1000),
];
const metadata = {
  schemaVersion: 1,
  collapsed: true,
  sections: [
    { title: 'Getting started', pages: [{ file: 'index.md', label: 'Overview' }, 'quickstart.md'] },
    { title: 'CLI', directory: 'cli', order: ['index.md', 'search.md', 'map.md'] },
    { title: 'Reference', generated: 'rust-api' },
  ],
};

test('comments and trailing commas can remove Guides and Reference from a human-edited navigation file', () => {
  const metadata = parseNavigationMetadata(`{
		"schemaVersion": 1,
		"sections": [
			{ "title": "Start // here", "pages": ["index.md",], },
			// { "title": "Guides", "directory": "guides" },
			/* { "title": "Reference", "generated": "rust-api" } */
		],
	}`);
  assert.deepEqual(
    resolveNavigation(pages, metadata).children.map((node) => node.title),
    ['Start // here'],
  );
});

test('malformed navigation JSON is rejected instead of accepting a partially parsed object', () => {
  assert.throws(
    () => parseNavigationMetadata('{\n "schemaVersion": 1, "sections": [invalid]\n}'),
    /_navigation.json: line 2, column/,
  );
  assert.throws(() => parseNavigationMetadata(''), /ValueExpected/);
  assert.throws(
    () => resolveNavigation(pages, parseNavigationMetadata('null')),
    /must be an object/,
  );
});

test('metadata owns section labels/order, explicit page labels, and directory priorities', () => {
  const tree = resolveNavigation(pages, metadata);
  assert.deepEqual(
    tree.children.map((node) => node.title),
    ['Getting started', 'CLI', 'Reference'],
  );
  assert.equal(tree.children[0].children[0].title, 'Overview');
  assert.equal(tree.children[1].id, 'cli');
  assert.deepEqual(
    tree.children[1].children.map((node) => node.title),
    ['Search', 'Map'],
  );
  assert.ok(tree.children.every((node) => node.collapsed));
});

test('new directory pages are discovered within configured sections; unlisted sections stay hidden', () => {
  const tree = resolveNavigation(
    [
      ...pages,
      page('cli/new.md', 'cli/new', 'New command'),
      page('new-guide.md', 'new-guide', 'New guide'),
    ],
    metadata,
  );
  assert.deepEqual(
    tree.children.map((node) => node.title),
    ['Getting started', 'CLI', 'Reference'],
  );
  assert.deepEqual(
    tree.children[1].children.map((node) => node.title),
    ['Search', 'Map', 'New command'],
  );
  assert.equal(tree.children[2].route, 'api');
});

test('removing explicit pages or sections removes their navigation without changing the page inventory', () => {
  const tree = resolveNavigation(pages, {
    schemaVersion: 1,
    sections: [{ title: 'Getting started', pages: ['index.md'] }],
  });
  assert.deepEqual(
    tree.children.map((node) => node.title),
    ['Getting started'],
  );
  assert.deepEqual(
    tree.children[0].children.map((node) => node.id),
    ['index'],
  );
  assert.equal(pages.length, 7);
  assert.ok(pages.some((page) => page.route === 'api'));
  assert.ok(pages.some((page) => page.route === 'cli/map'));
});

test('missing, excluded, duplicate, and overlapping page assignments fail', () => {
  assert.throws(
    () =>
      resolveNavigation(pages, {
        ...metadata,
        sections: [{ title: 'Missing', pages: ['README.md'] }],
      }),
    /missing published/,
  );
  assert.throws(
    () =>
      resolveNavigation(pages, {
        ...metadata,
        sections: [{ title: 'Private', pages: ['_private.md'] }],
      }),
    /relative public/,
  );
  assert.throws(
    () =>
      resolveNavigation(pages, {
        ...metadata,
        sections: [...metadata.sections, { title: 'Again', pages: ['cli/map.md'] }],
      }),
    /assigned more than once/,
  );
  assert.throws(
    () =>
      resolveNavigation(pages, {
        ...metadata,
        sections: [{ title: 'CLI', directory: 'cli', order: ['missing.md'] }],
      }),
    /ordered page missing/,
  );
});

test('unsupported versions/fields, traversal, and malformed selectors fail before consumption', () => {
  assert.throws(() => resolveNavigation(pages, { ...metadata, schemaVersion: 2 }), /schemaVersion/);
  assert.throws(() => resolveNavigation(pages, { ...metadata, arbitrary: true }), /unknown field/);
  assert.throws(
    () =>
      resolveNavigation(pages, {
        ...metadata,
        sections: [{ title: 'Escape', directory: '../outside' }],
      }),
    /relative public/,
  );
  assert.throws(
    () =>
      resolveNavigation(pages, {
        ...metadata,
        sections: [{ title: 'Both', directory: 'cli', pages: ['index.md'] }],
      }),
    /exactly one/,
  );
});

test('an omitted Reference stays hidden and authored overview-only sections remain visible', () => {
  const tree = resolveNavigation(pages, {
    schemaVersion: 1,
    sections: [{ title: 'CLI', directory: 'cli' }],
  });
  assert.deepEqual(
    tree.children.map((node) => node.title),
    ['CLI'],
  );
  const single = resolveNavigation([page('concepts/index.md', 'concepts', 'Concepts')], {
    schemaVersion: 1,
    sections: [{ title: 'Concepts', directory: 'concepts' }],
  });
  assert.equal(single.children[0].id, 'concepts');
});

test('an explicitly empty section list means an empty sidebar', () => {
  assert.deepEqual(resolveNavigation(pages, { schemaVersion: 1, sections: [] }).children, []);
});
