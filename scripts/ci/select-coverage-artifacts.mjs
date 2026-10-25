import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Failed attempts retain browser logs under the same artifact name. Select
// each partition's newest upload by creation time, not API order or numeric ID.
export function selectCoverageArtifacts(artifacts) {
	return [1, 2].map((partition) => {
		const name = `rust-ci-coverage-all-features-${partition}`;
		const matches = artifacts.filter((item) => item.name === name && !item.expired);
		if (!matches.length) throw new Error(`Missing current coverage artifact: ${name}`);
		for (const item of matches) {
			if (!Number.isSafeInteger(item.id) || item.id <= 0 || !Number.isFinite(Date.parse(item.created_at))) {
				throw new Error(`Invalid coverage artifact identity: ${name}`);
			}
		}
		matches.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.id - a.id);
		return matches[0].id;
	});
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	const pages = JSON.parse(readFileSync(0, 'utf8'));
	if (!Array.isArray(pages) || pages.some((page) => !Array.isArray(page.artifacts))) {
		throw new Error('Expected paginated workflow-run artifact responses');
	}
	console.log(`ids=${selectCoverageArtifacts(pages.flatMap((page) => page.artifacts)).join(',')}`);
}
