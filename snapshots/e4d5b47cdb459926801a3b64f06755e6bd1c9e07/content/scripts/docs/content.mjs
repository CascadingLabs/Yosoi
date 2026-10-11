import { cp, mkdir, readdir, readFile, lstat } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { parseFrontmatter } from './generate.mjs';
import { parseNavigationMetadata } from './navigation.mjs';

export async function copyPublicTree(source, target, prefix = '') {
  for (const entry of (await readdir(source, { withFileTypes: true })).sort((a, b) =>
    a.name.localeCompare(b.name),
  )) {
    if (entry.name.startsWith('_') || /^(agents|readme)\.md$/i.test(entry.name)) continue;
    if (entry.isSymbolicLink())
      throw new Error(`Public docs must not contain symlinks: ${prefix}${entry.name}`);
    const relative = `${prefix}${entry.name}`;
    if (entry.isDirectory())
      await copyPublicTree(path.join(source, entry.name), target, `${relative}/`);
    else if (entry.isFile()) {
      if (relative.endsWith('.mdx')) {
        const { metadata } = parseFrontmatter(
          await readFile(path.join(source, entry.name), 'utf8'),
          relative,
        );
        if (metadata.draft === true) continue;
        throw new Error(
          `${relative}: MDX publication is not supported yet; mark the page draft: true.`,
        );
      }
      if (!relative.endsWith('.md') && !/^(assets|media)\//.test(relative))
        throw new Error(
          `${relative}: unsupported public file; use Markdown or put assets under assets/.`,
        );
      const normalized = relative.replace(/^media\//, 'assets/media/');
      const destination = path.join(target, normalized);
      await mkdir(path.dirname(destination), { recursive: true });
      await cp(path.join(source, entry.name), destination);
    }
  }
}

export function rewriteMarkdownLinks(tree, file, pages, assets) {
  const href = (route) => `/yosoi/${route ? `${route}/` : ''}`;
  function visit(node) {
    if (
      ['link', 'image', 'definition'].includes(node.type) &&
      node.url &&
      !/^(?:[a-z][a-z\d+.-]*:|\/\/|#)/i.test(node.url)
    ) {
      const url = new URL(node.url, `https://docs.local/${file}`);
      const target = decodeURIComponent(url.pathname).slice(1);
      const page = pages.get(target) || pages.get(`${target.replace(/\/$/, '')}/index.md`);
      const asset = assets.has(target) ? target : target.replace(/^media\//, 'assets/media/');
      if (page) node.url = `${href(page.route)}${url.search}${url.hash}`;
      else if (assets.has(asset))
        node.url = `/yosoi/assets/${asset.slice('assets/'.length)}${url.search}${url.hash}`;
      else if (!node.url.startsWith('/'))
        throw new Error(`${file}: local link has no published target: ${node.url}`);
    }
    for (const child of node.children || []) visit(child);
  }
  visit(tree);
  return tree;
}

export async function readPublicNavigation(root, parser) {
  const file = path.join(root, '_navigation.json');
  try {
    const stat = await lstat(file);
    if (!stat.isFile()) throw new Error('_navigation.json must be a regular file.');
    const bytes = await readFile(file);
    return {
      metadata: parseNavigationMetadata(bytes.toString('utf8'), parser),
      source: {
        path: '_navigation.json',
        sha256: createHash('sha256').update(bytes).digest('hex'),
      },
    };
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    return {};
  }
}

export function authoredPages(manifest) {
  const pages = Object.entries(manifest.pages).map(([route, item]) => ({
    ...item,
    route: route === '/' ? '' : route.slice(1),
    id: route === '/' ? 'index' : route.slice(1),
  }));
  if (
    pages.some((page) =>
      ['api', 'archive', 'assets'].some(
        (reserved) => page.route === reserved || page.route.startsWith(`${reserved}/`),
      ),
    )
  )
    throw new Error(
      'The api/, archive/, and assets/ routes are reserved by the documentation frontend.',
    );
  return pages;
}

export function validateDocHeadings(tree, file) {
  const titles = tree.children.flatMap((node, index) =>
    node.type === 'heading' && node.depth === 1 ? [index] : [],
  );
  if (titles.length > 1 || (titles.length === 1 && titles[0] !== 0))
    throw new Error(`${file}: use at most one leading H1; Starlight renders the page title.`);
}
