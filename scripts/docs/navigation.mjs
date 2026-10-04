const compare = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const fail = (message) => {
  throw new Error(`_navigation.json: ${message}`);
};
const object = (value) => value && typeof value === 'object' && !Array.isArray(value);
const keys = (value, allowed) => {
  for (const key of Object.keys(value)) if (!allowed.includes(key)) fail(`unknown field ${key}`);
};
const text = (value, field) => {
  if (typeof value !== 'string' || !value.trim()) fail(`${field} must be a nonempty string`);
  return value;
};
const safePath = (value, field) => {
  text(value, field);
  if (
    value.startsWith('/') ||
    value.includes('\\') ||
    value
      .split('/')
      .some((part) => !part || part === '.' || part === '..' || part.startsWith('_')) ||
    /[?#%]/.test(value) ||
    [...value].some(
      (character) => character.codePointAt(0) < 32 || character.codePointAt(0) === 127,
    )
  )
    fail(`${field} must be a relative public path`);
  return value;
};
const isReference = (page) => page.route === 'api' || page.route.startsWith('api/');
const pageNode = (page, label = page.title) => ({
  title: label,
  route: page.route,
  id: page.id,
  order: page.order,
  children: [],
});
const pageCompare = (a, b) =>
  a.order - b.order || compare(a.title, b.title) || compare(a.route, b.route);

export function parseNavigationMetadata(source, { parse, printParseErrorCode }) {
  const errors = [];
  const value = parse(source, errors, { allowTrailingComma: true, disallowComments: false });
  if (errors.length) {
    const error = errors[0];
    const lines = source.slice(0, error.offset).split(/\r\n|\r|\n/);
    fail(
      `line ${lines.length}, column ${lines.at(-1).length + 1}: ${printParseErrorCode(error.error)}`,
    );
  }
  return value;
}

export function directoryNavigation(pages, directory, title) {
  const root = { title, route: directory, order: 0, children: [] };
  for (const page of pages) {
    const segments =
      page.route === directory
        ? []
        : page.route
            .slice(directory ? directory.length + 1 : 0)
            .split('/')
            .filter(Boolean);
    let node = root;
    for (let i = 0; i < segments.length; i++) {
      const route = [directory, ...segments.slice(0, i + 1)].filter(Boolean).join('/');
      let child = node.children.find((item) => item.route === route);
      if (!child) {
        child = {
          title: segments[i].replaceAll('-', ' '),
          route,
          order: Number.MAX_SAFE_INTEGER,
          children: [],
        };
        node.children.push(child);
      }
      node = child;
    }
    node.id = page.id;
    node.order = page.order;
    if (node !== root) node.title = page.title;
  }
  const sort = (node) => {
    node.children.sort(pageCompare);
    node.children.forEach(sort);
  };
  sort(root);
  return root;
}

// Public Rust paths own display namespaces; route paths keep their existing item-kind segments.
export function referenceNavigation(pages, title = 'Reference') {
  const root = { title, route: 'api', order: 0, collapsed: true, children: [] };
  const groups = new Map([['', root]]);
  const label = (name) => name.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());
  const group = (namespace) => {
    const key = namespace.join('::');
    if (groups.has(key)) return groups.get(key);
    const parent = group(namespace.slice(0, -1));
    const node = { title: label(namespace.at(-1)), route: `api/${namespace.map((name) => name.replaceAll('_', '-').toLowerCase()).join('/')}`, order: 0, collapsed: true, children: [] };
    parent.children.push(node); groups.set(key, node); return node;
  };
  const kinds = new Set(['module', 'enum', 'struct', 'function', 'trait', 'type_alias', 'proc_macro', 'reexport', 'union', 'constant', 'static']);
  for (const page of pages) {
    if (page.route === 'api') { root.id = page.id; continue; }
    const path = page.publicPath?.split('::');
    const segments = page.route.slice('api/'.length).split('/');
    const kindIndex = segments.findIndex((segment) => kinds.has(segment));
    const kind = page.kind || segments[kindIndex];
    const namespace = path ? path.slice(1, kind === 'module' ? undefined : -1) : segments.slice(1, kindIndex < 0 ? -1 : kindIndex);
    if (!path && kind === 'module') namespace.push(segments.at(-1));
    const parent = group(namespace);
    if (kind === 'module') { parent.id = page.id; parent.route = page.route; }
    else parent.children.push({ ...pageNode(page), kind });
  }
  const sort = (node) => {
    node.children.sort((a, b) => compare(a.title.toLowerCase(), b.title.toLowerCase()) || compare(a.route, b.route));
    node.children.forEach(sort);
  };
  sort(root); return root;
}

export function resolveNavigation(pages, metadata) {
  if (!object(metadata)) fail('must be an object');
  keys(metadata, ['schemaVersion', 'collapsed', 'sections']);
  if (metadata.schemaVersion !== 1) fail('unsupported schemaVersion');
  if (metadata.collapsed !== undefined && typeof metadata.collapsed !== 'boolean')
    fail('collapsed must be boolean');
  if (!Array.isArray(metadata.sections)) fail('sections must be an array');
  const byFile = new Map(pages.map((page) => [page.file, page]));
  const claimed = new Set();
  const claim = (page) => {
    if (claimed.has(page.id)) fail(`page assigned more than once: ${page.file}`);
    claimed.add(page.id);
    return page;
  };
  const lookup = (file) => {
    safePath(file, 'page');
    const page = byFile.get(file);
    if (!page || isReference(page)) fail(`missing published Markdown page: ${file}`);
    return page;
  };
  const sections = [];
  const labels = new Set();
  for (const [index, section] of metadata.sections.entries()) {
    if (!object(section)) fail(`section ${index + 1} must be an object`);
    keys(section, ['title', 'pages', 'directory', 'generated', 'order', 'collapsed']);
    const title = text(section.title, 'section title');
    if (labels.has(title)) fail(`duplicate section title: ${title}`);
    labels.add(title);
    if (
      ['pages', 'directory', 'generated'].filter((key) => section[key] !== undefined).length !== 1
    )
      fail(`${title} must select exactly one of pages, directory, or generated`);
    if (section.collapsed !== undefined && typeof section.collapsed !== 'boolean')
      fail(`${title}: collapsed must be boolean`);
    const collapsed = section.collapsed ?? metadata.collapsed ?? true;
    let node;
    if (section.pages !== undefined) {
      if (section.order !== undefined) fail(`${title}: order is only valid for directory sections`);
      if (!Array.isArray(section.pages) || !section.pages.length)
        fail(`${title}: pages must be a nonempty array`);
      const children = section.pages.map((entry) => {
        if (typeof entry === 'string') return pageNode(claim(lookup(entry)));
        if (!object(entry)) fail(`${title}: invalid page entry`);
        keys(entry, ['file', 'label']);
        const page = claim(lookup(entry.file));
        return pageNode(
          page,
          entry.label === undefined ? page.title : text(entry.label, 'page label'),
        );
      });
      node = { title, route: '', order: index, children };
    } else {
      const generated = section.generated !== undefined;
      if (generated && section.generated !== 'rust-api')
        fail(`unknown generated section: ${section.generated}`);
      if (generated && section.order !== undefined)
        fail('generated reference pages manage their own order');
      const directory = generated ? 'api' : safePath(section.directory, 'directory');
      const selected = pages.filter(
        (page) => page.route === directory || page.route.startsWith(`${directory}/`),
      );
      if (!selected.length || (!generated && selected.some(isReference)))
        fail(`${title}: no authored pages in directory ${directory}`);
      let ordered = selected.map((page) => ({ ...page }));
      if (section.order !== undefined) {
        if (!Array.isArray(section.order)) fail(`${title}: order must be an array`);
        const priority = new Map();
        for (const [position, file] of section.order.entries()) {
          safePath(file, 'ordered page');
          const full = `${directory}/${file}`;
          if (!selected.some((page) => page.file === full))
            fail(`${title}: ordered page missing: ${full}`);
          if (priority.has(full)) fail(`${title}: duplicate ordered page: ${full}`);
          priority.set(full, position);
        }
        ordered = ordered.map((page) => ({
          ...page,
          order: priority.get(page.file) ?? priority.size + 1 + page.order,
        }));
      }
      selected.forEach(claim);
      node = generated ? referenceNavigation(ordered, title) : directoryNavigation(ordered, directory, title);
    }
    node.order = index;
    node.collapsed = collapsed;
    sections.push(node);
  }
  return {
    title: 'Yosoi',
    route: '',
    order: -1,
    collapsed: metadata.collapsed ?? true,
    children: sections,
  };
}
