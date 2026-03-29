#!/usr/bin/env node
/**
 * Puppeteer benchmark helper — called by bench_all.py via subprocess.
 *
 * Outputs JSON lines to stdout with timing and content metrics.
 * Usage: node benchmarks/bench_puppeteer.mjs <url> <runs> <parallel> [--headless]
 */

import puppeteer from 'puppeteer';

const args = process.argv.slice(2);
const url = args[0];
const runs = parseInt(args[1], 10);
const parallel = parseInt(args[2], 10);
const headless = args.includes('--headless') ? 'new' : false;

const MIN_CONTENT_LEN = 10_000;

function chromeRssMB() {
  // Not easily available from Node — report 0, Python will measure externally.
  return 0;
}

async function main() {
  const result = {
    name: 'puppeteer (Node.js)',
    cold_start: 0,
    single_fetches: [],
    parallel_time: 0,
    parallel_count: 0,
    html_lengths: [],
    blocked: 0,
  };

  const t0 = performance.now();
  const browser = await puppeteer.launch({ headless, args: ['--no-sandbox'] });
  result.cold_start = (performance.now() - t0) / 1000;

  async function fetchPage() {
    const t = performance.now();
    const page = await browser.newPage();
    await page.goto(url, { waitUntil: 'networkidle0', timeout: 30000 });
    const html = await page.content();
    await page.close();
    const elapsed = (performance.now() - t) / 1000;
    const length = html.length;
    const blocked = html.includes('Access Denied') || length < MIN_CONTENT_LEN;
    return { length, elapsed, blocked };
  }

  // Sequential runs
  for (let i = 0; i < runs; i++) {
    const { length, elapsed, blocked } = await fetchPage();
    result.single_fetches.push(elapsed);
    result.html_lengths.push(length);
    if (blocked) result.blocked++;
    const status = blocked ? 'BLOCKED' : `${length.toLocaleString()} chars`;
    process.stderr.write(`  puppeteer [${i + 1}/${runs}]: ${elapsed.toFixed(2)}s  ${status}\n`);
  }

  // Parallel runs
  if (parallel > 1) {
    process.stderr.write(`  puppeteer parallel [${parallel} tabs]...\n`);
    const t2 = performance.now();
    const results = await Promise.all(Array.from({ length: parallel }, () => fetchPage()));
    result.parallel_time = (performance.now() - t2) / 1000;
    result.parallel_count = parallel;
    for (const { length, elapsed, blocked } of results) {
      result.html_lengths.push(length);
      if (blocked) result.blocked++;
      const status = blocked ? 'BLOCKED' : `${length.toLocaleString()} chars`;
      process.stderr.write(`    tab: ${elapsed.toFixed(2)}s  ${status}\n`);
    }
  }

  await browser.close();

  // Output JSON to stdout for Python to parse
  process.stdout.write(JSON.stringify(result) + '\n');
}

main().catch((err) => {
  process.stderr.write(`puppeteer error: ${err.message}\n`);
  process.exit(1);
});
