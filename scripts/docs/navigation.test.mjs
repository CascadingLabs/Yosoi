import assert from 'node:assert/strict';
import { test } from 'vite-plus/test';
import {
  parseNavigationMetadata as decode,
  referenceNavigation,
  resolveNavigation,
} from './navigation.mjs';
import * as jsonc from 'jsonc-parser';
import { authoredPages } from './content.mjs';
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

test('Python symbol kinds reach navigation without treating overview pages as symbols', () => {
  const routes = {
    '/python-api': 'Python reference',
    '/python-api/browser/types/flow': 'Flow',
    '/python-api/browser/functions/navigate': 'navigate',
    '/python-api/browser/aliases/positive-u64': 'PositiveU64',
    '/python-api/browser/constants/default-timeout': 'DEFAULT_TIMEOUT',
  };
  const inventory = authoredPages({
    pages: Object.fromEntries(
      Object.entries(routes).map(([route, title]) => [
        route,
        {
          file: `${route.slice(1)}.md`,
          title,
          order: 0,
        },
      ]),
    ),
  });
  const tree = resolveNavigation(inventory, {
    schemaVersion: 1,
    sections: [{ title: 'Python', directory: 'python-api' }],
  });
  const nodes = (node) => [node, ...node.children.flatMap(nodes)];
  const symbols = nodes(tree).filter((node) => node.kind);
  assert.deepEqual(Object.fromEntries(symbols.map((node) => [node.title, node.kind])), {
    PositiveU64: 'type_alias',
    DEFAULT_TIMEOUT: 'constant',
    navigate: 'function',
    Flow: 'class',
  });
  assert.equal(tree.children[0].kind, undefined);
  assert.ok(symbols.every((node) => node.children.length === 0));
});

test('Reference nests Rust and Python without allowing pages to be assigned twice', () => {
  const python = page('python-api/index.md', 'python-api', 'Python reference');
  const inventory = [...pages, python];
  const reference = {
    title: 'Reference',
    sections: [
      { title: 'Rust', generated: 'rust-api' },
      { title: 'Python', directory: 'python-api' },
    ],
  };
  const tree = resolveNavigation(inventory, { schemaVersion: 1, sections: [reference] });
  assert.deepEqual(
    tree.children.map((node) => node.title),
    ['Reference'],
  );
  assert.deepEqual(
    tree.children[0].children.map((node) => node.title),
    ['Rust', 'Python'],
  );
  assert.equal(tree.children[0].children[0].id, 'api');
  assert.equal(tree.children[0].children[1].id, 'python-api');
  assert.throws(
    () =>
      resolveNavigation(inventory, {
        schemaVersion: 1,
        sections: [reference, { title: 'Again', pages: ['python-api/index.md'] }],
      }),
    /assigned more than once/,
  );
});

test('release navigation hides candidates and orders final versions numerically newest first', () => {
  const releases = [
    page('releases/index.md', 'releases', 'Release notes'),
    ...['0.1.0', '0.1.0-rc.8', '0.10.0', '0.2.0', '0.1.2', '0.3.0-rc.1'].map((version) => ({
      ...page(
        `releases/${version.replaceAll('.', '-')}.md`,
        `releases/${version.replaceAll('.', '-')}`,
        `Yosoi ${version} release notes`,
      ),
      version,
    })),
  ];
  const tree = resolveNavigation(releases, {
    schemaVersion: 1,
    sections: [{ title: 'Release notes', directory: 'releases', order: ['index.md'] }],
  });
  assert.equal(tree.children[0].id, 'releases');
  assert.deepEqual(
    tree.children[0].children.flatMap((node) => node.children.map((child) => child.route)),
    ['releases/0-10-0', 'releases/0-2-0', 'releases/0-1-2', 'releases/0-1-0'],
  );
  assert.deepEqual(
    tree.children[0].children.map((node) => node.title),
    ['0.10.x', '0.2.x', '0.1.x'],
  );
  assert.deepEqual(
    tree.children[0].children[2].children.map((node) => node.title),
    ['0.1.2', '0.1.0'],
  );
  assert.equal(tree.children[0].children[2].collapsed, true);
  assert.equal(releases[1].title, 'Yosoi 0.1.0 release notes');
  assert.equal(releases.length, 7);
});

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

test('generated reference uses public namespaces rather than route kind folders', () => {
  const references = [
    { ...page('api/index.md', 'api', 'Reference'), kind: 'module', publicPath: 'yosoi' },
    {
      ...page('api/locators.md', 'api/yosoi/module/locators', 'Locators'),
      kind: 'module',
      publicPath: 'yosoi::locators',
    },
    {
      ...page('api/z.md', 'api/yosoi/locators/struct/zeta', 'Zeta'),
      kind: 'struct',
      publicPath: 'yosoi::locators::Zeta',
    },
    {
      ...page('api/a.md', 'api/yosoi/locators/enum/alpha', 'Alpha'),
      kind: 'enum',
      publicPath: 'yosoi::locators::Alpha',
    },
  ];
  const tree = referenceNavigation(references);
  assert.deepEqual(
    tree.children.map((node) => node.title),
    ['Modules'],
  );
  assert.deepEqual(
    tree.children[0].children[0].children[0].children.map((node) => node.title),
    ['Alpha', 'Zeta'],
  );
  assert.equal(tree.children[0].children[0].children[0].title, 'Types');
  assert.equal(
    tree.children[0].children[0].children[0].children[0].route,
    'api/yosoi/locators/enum/alpha',
  );
  const configured = resolveNavigation(references, {
    schemaVersion: 1,
    sections: [{ title: 'Reference', generated: 'rust-api' }],
  });
  assert.deepEqual(
    configured.children[0].children.map((node) => node.title),
    ['Modules'],
  );
});
