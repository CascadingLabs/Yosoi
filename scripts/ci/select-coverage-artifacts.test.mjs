import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { selectCoverageArtifacts } from './select-coverage-artifacts.mjs';

const artifact = (partition, id, created_at, expired = false) => ({
	name: `rust-ci-coverage-all-features-${partition}`, id, created_at, expired,
});
const first = artifact(1, 90, '2026-10-25T04:31:36Z');
const failedSecond = artifact(2, 100, '2026-10-25T04:30:30Z');
const successfulSecond = artifact(2, 80, '2026-10-25T04:49:50Z');

test('retried partition selects the new upload despite its lower ID and API position', () => {
	assert.deepEqual(selectCoverageArtifacts([first, failedSecond, successfulSecond]), [90, 80]);
	assert.deepEqual(selectCoverageArtifacts([successfulSecond, first, failedSecond]), [90, 80]);
});

test('expired uploads cannot replace an available partition', () => {
	assert.deepEqual(selectCoverageArtifacts([
		first, successfulSecond, artifact(2, 200, '2026-10-25T05:00:00Z', true),
	]), [90, 80]);
});

test('both partitions are mandatory', () => {
	assert.throws(() => selectCoverageArtifacts([first]), /Missing current coverage artifact/);
	assert.throws(() => selectCoverageArtifacts([first, { ...successfulSecond, expired: true }]), /Missing current coverage artifact/);
});

test('malformed timestamps and IDs fail rather than falling back to an old upload', () => {
	assert.throws(() => selectCoverageArtifacts([first, failedSecond, { ...successfulSecond, created_at: 'invalid' }]), /Invalid coverage artifact identity/);
	assert.throws(() => selectCoverageArtifacts([first, { ...successfulSecond, id: 0 }]), /Invalid coverage artifact identity/);
});

test('CLI reads all API pages and emits only the selected immutable IDs', () => {
	const result = spawnSync(process.execPath, [fileURLToPath(new URL('./select-coverage-artifacts.mjs', import.meta.url))], {
		input: JSON.stringify([{ artifacts: [first, failedSecond] }, { artifacts: [successfulSecond] }]), encoding: 'utf8',
	});
	assert.equal(result.status, 0, result.stderr);
	assert.equal(result.stdout.trim(), 'ids=90,80');
});
