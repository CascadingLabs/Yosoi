// Usage: bun summarize-yielding.mjs comparison.json > comparison.md
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const path = process.argv[2];
if (!path) throw new Error('Pass comparison.json');
const bytes = await readFile(path);
const data = JSON.parse(bytes);
const median = (values) => {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const index = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[index] : (sorted[index - 1] + sorted[index]) / 2;
};
const fixed = (value, digits = 2) => value == null ? 'unavailable' : value.toFixed(digits);
const measured = (item) => item.rounds.filter((round) => !round.warmup);
const summary = (item) => {
  const rounds = measured(item);
  const times = rounds.map((round) => round.elapsed_ms / 1000);
  const anchors = item.scenario.latency_ms >= 3000 ? item.scenario.workers : 1;
  const admission = rounds.flatMap((round) => (round.jobs ?? [])
    .filter((job) => job.id >= anchors)
    .map((job) => (job.service_request_ms - job.submitted_ms) / 1000));
  const memory = (key, divisor) => median(rounds.map((round) =>
    round.memory[key] == null ? NaN : round.memory[key] / divisor));
  return { count: rounds.length, time:median(times), min:Math.min(...times), max:Math.max(...times),
    throughput:median(rounds.map((round)=>round.completed_jobs_per_second)), admission:median(admission),
    cgroup:memory('cgroup_bytes', 1048576), chrome:memory('chrome_pss_kib', 1024), sdk:memory('sdk_rss_kib', 1024) };
};
const groups = new Map();
for (const item of data.cases) {
  const group = groups.get(item.scenario.name) ?? {};
  group[item.rounds[0]?.mode] = summary(item);
  groups.set(item.scenario.name, group);
}
const paired = [...groups].filter(([,group]) => group['retain-worker'] && group.yield);
console.log('# Yielding under I/O load\n');
console.log(`Source: \`${data.source}\`  \nBrowser: ${data.browser}  \nController/schema: ${data.controller}  \nFramework: ${data.framework ?? 'pre-HTMX fixture'}  \nInput SHA-256: \`${createHash('sha256').update(bytes).digest('hex')}\`\n`);
console.log('Each policy uses an owned browser with the same tab/worker limits. Startup is separate; the first round is an excluded warmup. Values below are warm medians, with batch ranges in parentheses. This measures batch throughput and responsiveness under I/O load, not faster individual actions.\n');
console.log('| Scenario | Retain worker: batch seconds | Yield: batch seconds | Completed jobs/s: retain / yield | Later-job submission to service: retain / yield seconds |');
console.log('| --- | --- | --- | --- | --- |');
for (const [name, group] of paired) {
  const a=group['retain-worker'], b=group.yield;
  console.log(`| ${name} | ${fixed(a.time)} (${fixed(a.min)}–${fixed(a.max)}) | ${fixed(b.time)} (${fixed(b.min)}–${fixed(b.max)}) | ${fixed(a.throughput,3)} / ${fixed(b.throughput,3)} | ${fixed(a.admission)} / ${fixed(b.admission)} |`);
}
console.log('\n## Sampled memory\n');
console.log('| Scenario | Cgroup MiB: retain / yield | Chrome PSS MiB: retain / yield | SDK RSS MiB: retain / yield |');
console.log('| --- | --- | --- | --- |');
for (const [name, group] of paired) {
  const a=group['retain-worker'], b=group.yield;
  console.log(`| ${name} | ${fixed(a.cgroup)} / ${fixed(b.cgroup)} | ${fixed(a.chrome)} / ${fixed(b.chrome)} | ${fixed(a.sdk)} / ${fixed(b.sdk)} |`);
}
console.log('\nMemory is sampled every 100 ms plus a final sample. Cgroup usage includes SDK, browser, cache and kernel charges; Chrome PSS and SDK RSS use different accounting and must not be subtracted from it. Shared file charges can reside outside a container. These measurements do not establish a universal memory increase or decrease. Three repeats and fixed policy order are preliminary evidence, not a statistically controlled performance ranking.\n');
console.log('Admission here includes navigation/setup and controller queues: it is the server-observed request timestamp minus the application submission timestamp, not a pure semaphore timing. A constrained upstream or browser HTTP/1 connection pool can limit throughput even when controller slots are available. Foreground input and screenshot capture remain serialized by the browser surface lock.\n');
if (paired.length !== groups.size) console.log('**Partial input:** an unpaired policy case is still in progress.');
