import { mkdir, mkdtemp, readFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as jsonc from 'jsonc-parser';
import { markdownToMdast, markdownToHtml } from 'satteri';
import { toMarkdown } from 'mdast-util-to-markdown';
import { gfmToMarkdown } from 'mdast-util-gfm';
import { generatePreview, parseFrontmatter } from './generate.mjs';
import { resolveNavigation } from './navigation.mjs';
import {
  authoredPages,
  copyPublicTree,
  readPublicNavigation,
  rewriteMarkdownLinks,
  validateDocHeadings,
} from './content.mjs';

export const publicRoot = fileURLToPath(new URL('../../docs/public/', import.meta.url));
export async function validatePublicDocs(root = publicRoot) {
  const work = fileURLToPath(new URL('../../.generated/docs-check/', import.meta.url));
  await mkdir(work, { recursive: true });
  const stage = await mkdtemp(path.join(work, 'snapshot-'));
  try {
    await copyPublicTree(root, stage);
    const manifest = generatePreview({
      root: stage,
      version: '0.0.0-preview',
      repository: 'CascadingLabs/Yosoi',
      sourceCommit: '0'.repeat(40),
    });
    const pages = authoredPages(manifest);
    const nav = await readPublicNavigation(root, jsonc);
    // Validate the generated section selector without compiling or claiming to verify Rust API output.
    const reference = {
      file: 'api/index.md',
      route: 'api',
      id: 'api',
      title: 'Reference',
      order: 1000,
    };
    const navigation = nav.source
      ? resolveNavigation([...pages, reference], nav.metadata)
      : undefined;
    const pageMap = new Map(pages.map((page) => [page.file, page]));
    const assets = new Set(Object.keys(manifest.assets));
    for (const page of pages) {
      const { body } = parseFrontmatter(
        await readFile(path.join(stage, page.file), 'utf8'),
        page.file,
      );
      const tree = await markdownToMdast(body, { features: { gfm: true } });
      validateDocHeadings(tree, page.file);
      rewriteMarkdownLinks(tree, page.file, pageMap, assets);
      const rewritten = toMarkdown(tree, { extensions: [gfmToMarkdown()] });
      await markdownToHtml(rewritten, { features: { gfm: true } });
    }
    return { pages, navigation, assets: assets.size };
  } finally {
    await rm(stage, { recursive: true, force: true });
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = await validatePublicDocs();
    console.log(
      `Validated ${result.pages.length} Markdown pages, ${result.assets} assets, and navigation; native Markdown rendering passed.`,
    );
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
