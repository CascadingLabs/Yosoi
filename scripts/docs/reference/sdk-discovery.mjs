import fs from 'node:fs';

export const sdkPolicy = JSON.parse(fs.readFileSync(new URL('./sdk-policy.json', import.meta.url), 'utf8'));

// Naming reserves intent; Cargo metadata is the explicit declaration of SDK ownership.
export function discoverSdks(metadata, policy = sdkPolicy) {
	if (policy.schemaVersion !== 1) throw new Error('Unsupported SDK policy');
	const names = new RegExp(policy.packageNamePattern);
	const workspace = new Set(metadata.workspace_members);
	const sdks = [];
	for (const pkg of metadata.packages.filter((item) => workspace.has(item.id))) {
		const reserved = names.test(pkg.name);
		const declared = pkg.metadata?.yosoi?.sdk === true;
		if (reserved && !declared) throw new Error(`${pkg.name} uses a reserved SDK name without package.metadata.yosoi.sdk = true`);
		if (!declared) continue;
		if (!reserved && !policy.legacySdkPackages.includes(pkg.name)) throw new Error(`${pkg.name} declares an SDK but does not match the SDK naming policy`);
		const library = pkg.targets.find((target) => target.kind.some((kind) => ['lib', 'rlib', 'cdylib'].includes(kind)));
		if (!library) throw new Error(`${pkg.name} declares an SDK without a public library target`);
		sdks.push({ name: pkg.name, crate: library.name, version: pkg.version, manifestPath: pkg.manifest_path, target: library });
	}
	if (!sdks.length) throw new Error('No declared SDK crates were found');
	return sdks.sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
}
