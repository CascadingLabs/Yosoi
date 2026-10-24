// Drive the public JSON-lines CLI through the docs version menu, then archive it.
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import fs from 'node:fs';
import path from 'node:path';

const binary = process.argv[2] ?? 'yosoi';
const output = path.resolve(process.argv[3] ?? 'docs-version-run');
const url = 'https://cascadinglabs.com/yosoi/getting-started/what-is-yosoi/';
fs.mkdirSync(output, { recursive: true });
const child = spawn(binary, ['surface', 'web', '--url', url, '--headless',
  '--archive', path.join(output, 'archive'), '--output', output],
  { stdio: ['pipe', 'pipe', 'inherit'], timeout: 120_000 });
const closed = new Promise((resolve, reject) => {
  child.once('error', reject);
  child.once('close', code => resolve(code));
});
const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
const transcript = [];
let sequence = 0;
let final = null;
let failure = null;
let passed = false;

async function next() {
  const line = await lines.next();
  if (line.done) throw Error('Surface CLI ended before replying');
  const value = JSON.parse(line.value);
  transcript.push(value);
  if (!value.ok) throw Error(value.error);
  return value;
}

async function send(command) {
  const id = String(++sequence);
  child.stdin.write(JSON.stringify({ ...command, id }) + '\n');
  const value = await next();
  if (value.id !== id) throw Error('Surface reply has another request identity');
  return value.result;
}

async function read(operation, continuation = null) {
  return send({ op: 'read', request: { operation, continuation,
    budget: { bytes: 3072, items: 20 } } });
}

async function locate(query, tag) {
  let continuation = null;
  const matches = new Map();
  do {
    const page = (await read({ kind: 'search', query }, continuation)).data;
    if (!page.coverage.complete) throw Error('Search has incomplete source coverage');
    for (const entry of page.entries) {
      let reference = entry.reference;
      for (let depth = 0; reference && depth < 8; depth++) {
        let detail = (await read({ kind: 'inspect', reference })).data;
        let content = detail.content;
        while (detail.next) {
          detail = (await read({ kind: 'inspect', reference }, detail.next)).data;
          content += detail.content;
        }
        if (JSON.parse(content).tag_name === tag) {
          matches.set(JSON.stringify(reference), reference);
          break;
        }
        reference = (await read({ kind: 'parent', reference })).data;
      }
    }
    continuation = page.next;
  } while (continuation);
  const eligible = [];
  for (const reference of matches.values()) {
    const focused = await send({ op: 'focus_evidence', reference });
    const checked = await send({ op: 'eligibility', reference: focused.cursor.position.focus });
    if (checked.eligible) eligible.push(reference);
  }
  if (eligible.length !== 1) throw Error(`Expected one eligible ${tag}, found ${eligible.length}`);
  return eligible[0];
}

try {
  const ready = await next();
  if (ready.result.event !== 'ready') throw Error('Missing ready event');
  await send({ op: 'attach' });
  await send({ op: 'hot' });
  for (const step of [
    { query: 'Documentation release', tag: 'summary',
      expect: { kind: 'text', text: 'v0.1.0', present: true } },
    { query: 'v0.1.0', tag: 'a', expect: { kind: 'text',
      text: 'This page is unavailable in v0.1.0. Showing the overview.', present: true } },
  ]) {
    const shared = await locate(step.query, step.tag);
    const focused = await send({ op: 'focus_evidence', reference: shared });
    const result = await send({ op: 'click', reference: focused.cursor.position.focus,
      target: { query: step.query, tag: step.tag }, expect: step.expect });
    if (result.receipt.status !== 'Confirmed') throw Error('Postcondition was not confirmed');
    if (step.query === 'v0.1.0') {
      const destination = new URL(result.outcome.postcondition.url);
      if (destination.origin !== new URL(url).origin || destination.pathname !== '/yosoi/archive/' || destination.searchParams.get('version') !== '0.1.0') {
        throw Error('The observed destination is not the requested archived version');
      }
    }
  }
  final = await send({ op: 'status' });
  await send({ op: 'close' });
  child.stdin.end();
  if (await closed !== 0) throw Error('Surface CLI failed during cleanup');
  passed = true;
  console.log(JSON.stringify({ passed: true, record: path.join(output, 'record.json') }));
} catch (error) {
  failure = String(error);
  throw error;
} finally {
  child.stdin.end();
  if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
  await closed.catch(error => { failure ??= String(error); passed = false; });
  fs.writeFileSync(path.join(output, 'example.json'), JSON.stringify({ passed,
    url, final, failure, transcript }, null, 2));
}
