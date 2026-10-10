import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { appendFile, lstat, mkdir, readFile, realpath, rm, utimes, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const snapshot = '.generated/ci-source-inputs/inputs.json';
const stateName = 'rust_source_cache_state';

async function inputs(root) {
  const files = execFileSync('git', ['-C', root, 'ls-files', '-z'], {
    encoding: 'utf8', maxBuffer: 16 * 1024 * 1024,
  }).split('\0').filter(Boolean).sort();
  const entries = [];
  for (const relative of files) {
    // Never read environment files or follow links into human configuration.
    if (/(^|\/)\.env(?:[./]|$)|\.env(?:[./]|$)/i.test(relative)) continue;
    const file = path.resolve(root, relative);
    if (!file.startsWith(root + path.sep)) throw new Error('Source escapes workspace');
    let stat;
    try { stat = await lstat(file); }
    catch (error) { if (error.code === 'ENOENT') continue; throw error; }
    if (!stat.isFile() || stat.isSymbolicLink() || await realpath(file) !== file) continue;
    const hash = createHash('sha256');
    for await (const chunk of createReadStream(file)) hash.update(chunk);
    entries.push({ path: relative, hash: hash.digest('hex'), mode: stat.mode,
      mtime: stat.mtimeMs });
  }
  return entries;
}

async function cached(root) {
  try {
    const text = await readFile(path.join(root, snapshot), 'utf8');
    if (text.length > 16 * 1024 * 1024) return new Map();
    const data = JSON.parse(text);
    if (data.version !== 1 || !Array.isArray(data.files)) return new Map();
    return new Map(data.files.filter(entry => typeof entry.path === 'string'
      && /^[a-f0-9]{64}$/.test(entry.hash) && Number.isInteger(entry.mode)
      && Number.isFinite(entry.mtime) && entry.mtime >= 0
      && entry.mtime <= Date.now()).map(entry => [entry.path, entry]));
  } catch (error) {
    if (error.code !== 'ENOENT') console.warn('Ignoring unusable source-cache metadata');
    return new Map();
  }
}

export async function prepare(root, stateFile) {
  root = await realpath(root);
  const previous = await cached(root);
  const current = await inputs(root);
  let restored = 0;
  for (const entry of current) {
    const old = previous.get(entry.path);
    if (old && old.hash === entry.hash && old.mode === entry.mode) {
      const file = path.join(root, entry.path);
      const stat = await lstat(file);
      await utimes(file, stat.atimeMs / 1000, old.mtime / 1000);
      entry.mtime = (await lstat(file)).mtimeMs;
      restored++;
    }
  }
  await writeFile(stateFile, JSON.stringify({ version: 1, root, files: current }));
  console.log(`Restored timestamps for ${restored} content-verified source files`);
}

export async function finish(stateFile) {
  const before = JSON.parse(await readFile(stateFile, 'utf8'));
  const current = await inputs(before.root);
  const destination = path.join(before.root, snapshot);
  const unchanged = current.length === before.files.length && current.every((entry, index) => {
    const old = before.files[index];
    return old.path === entry.path && old.hash === entry.hash && old.mode === entry.mode;
  });
  if (!unchanged) {
    await rm(destination, { force: true });
    console.log('Source changed during the job; normal Cargo freshness checks will apply');
    return;
  }
  await mkdir(path.dirname(destination), { recursive: true });
  // Retain the timestamps actually used by compilation, not later touches.
  await writeFile(destination, JSON.stringify({ version: 1, files: before.files }) + '\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.env[`STATE_${stateName}`]) {
    await finish(process.env[`STATE_${stateName}`]);
  } else {
    const stateFile = path.join(process.env.RUNNER_TEMP, `rust-source-${process.env.GITHUB_ACTION}.json`);
    await prepare(process.env.GITHUB_WORKSPACE, stateFile);
    await appendFile(process.env.GITHUB_STATE, `${stateName}=${stateFile}\n`);
  }
}
