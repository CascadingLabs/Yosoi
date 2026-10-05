import { expect, test } from 'vite-plus/test';
import { mkdtemp, mkdir, writeFile, rm, symlink } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validatePublicDocs } from './validate.mjs';
const work = fileURLToPath(new URL('../../.generated/docs-tests/', import.meta.url));
async function fixture(files, run) {
  await mkdir(work, { recursive: true });
  const root = await mkdtemp(path.join(work, 'source-'));
  try {
    for (const [file, body] of Object.entries({
      'index.md': '---\ntitle: Home\n---\n# Home\n',
      ...files,
    })) {
      await mkdir(path.dirname(path.join(root, file)), { recursive: true });
      await writeFile(path.join(root, file), body);
    }
    await run(root);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}
test('renders public Markdown with media and JSONC navigation using the frontend contract', async () => {
  await fixture(
    {
      'index.md': '# Home\n\n[Guide](guides/page.md#details)\n\n![Logo](media/logo.svg)\n',
      'guides/page.md': '# Guide\n\n## Details\n\n```rust\n// [Not a link](missing.md)\n```\n',
      'media/logo.svg': '<svg xmlns="http://www.w3.org/2000/svg"/>',
      '_navigation.json':
        '{"schemaVersion":1,"sections":[{"title":"Start","pages":["index.md"]}, // no guides\n ]}',
      'draft.mdx': '---\ndraft: true\n---\n<NotYetSupported/>',
      '_private.md': '# Not published\n[Broken](missing.md)',
      'AGENTS.md': '# Not published\n[Broken](missing.md)',
    },
    async (root) => {
      const result = await validatePublicDocs(root);
      expect(result.pages.map((page) => page.route)).toEqual(['', 'guides/page']);
      expect(result.assets).toBe(1);
      expect(result.navigation.children.map((node) => node.title)).toEqual(['Start']);
    },
  );
});
test('rejects broken links, missing assets, draft/private targets, and invalid frontmatter', async () => {
  for (const body of [
    '# Home\n[Broken](missing.md)',
    '# Home\n![Missing](assets/missing.png)',
    '# Home\n[Draft](draft.md)',
    '# Home\n[Private](_private.md)',
    '---\norder: nope\n---\n# Home',
  ]) {
    await fixture(
      {
        'index.md': body,
        'draft.md': '---\ndraft: true\n---\n# Draft',
        '_private.md': '# Private',
      },
      async (root) => {
        await expect(validatePublicDocs(root)).rejects.toThrow();
      },
    );
  }
});
test('rejects unsafe source paths, reserved API routes, unsupported formats, and duplicate page titles', async () => {
  for (const files of [
    { 'Unsafe.md': '# Bad' },
    { 'api/index.md': '# Reserved' },
    { 'component.mdx': '# Component\n<Callout title="Later">\nExample\n</Callout>' },
    { 'extra.txt': 'Unpublished text' },
    { 'index.md': '# First\n\n# Second' },
  ]) {
    await fixture(files, async (root) => {
      await expect(validatePublicDocs(root)).rejects.toThrow();
    });
  }
  await fixture({}, async (root) => {
    await symlink(path.join(root, 'index.md'), path.join(root, 'alias.md'));
    await expect(validatePublicDocs(root)).rejects.toThrow(/symlink/);
  });
});
test('rejects invalid, missing, draft, and duplicate navigation references', async () => {
  for (const nav of [
    'null',
    '{invalid}',
    '{"schemaVersion":1,"sections":[{"title":"Missing","pages":["missing.md"]}]}',
    '{"schemaVersion":1,"sections":[{"title":"Draft","pages":["draft.md"]}]}',
    '{"schemaVersion":1,"sections":[{"title":"Dup","pages":["index.md","index.md"]}]}',
  ]) {
    await fixture(
      { '_navigation.json': nav, 'draft.md': '---\ndraft: true\n---\n# Draft' },
      async (root) => {
        await expect(validatePublicDocs(root)).rejects.toThrow();
      },
    );
  }
});
