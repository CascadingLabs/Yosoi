import { readdir, readFile, writeFile, lstat } from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parseFrontmatter } from './generate.mjs';
const tooling = fileURLToPath(new URL('./', import.meta.url));
const root = fileURLToPath(new URL('../../docs/public/', import.meta.url));
const write = process.argv.includes('--write');
const files = [];
async function collect(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.name === '_navigation.json' && directory === root) {
      files.push(file);
      continue;
    }
    if (entry.name.startsWith('_') || /^(agents|readme).md$/i.test(entry.name)) continue;
    if (entry.isDirectory()) await collect(file);
    else if (entry.isFile() && /.(md|mdx)$/.test(entry.name)) {
      const source = await readFile(file, 'utf8');
      if (parseFrontmatter(source, path.relative(root, file)).metadata.draft !== true)
        files.push(file);
    }
  }
}
await collect(root);
let changed = false;
for (const file of files.sort()) {
  if (!(await lstat(file)).isFile()) throw new Error(`${file}: expected a regular file`);
  const source = await readFile(file, 'utf8');
  const formatted = execFileSync(
    'vp',
    [
      'fmt',
      '--stdin-filepath',
      file.endsWith('_navigation.json') ? file + 'c' : file,
      '--threads=1',
    ],
    { cwd: tooling, input: source, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] },
  );
  if (formatted !== source) {
    changed = true;
    if (write) await writeFile(file, formatted);
    else console.error(`Formatting required: ${path.relative(root, file)}`);
  }
}
execFileSync('vp', ['fmt', ...(write ? [] : ['--check']), '--threads=1'], {
  cwd: tooling,
  stdio: 'inherit',
});
if (changed && !write) {
  console.error('Run vpr fmt from scripts/docs, then retry.');
  process.exitCode = 1;
}
