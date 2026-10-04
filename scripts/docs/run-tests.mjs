import { mkdir } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const temp = fileURLToPath(new URL('../../.generated/docs-tests/runtime/', import.meta.url));
await mkdir(temp, { recursive: true });
execFileSync('vp', ['test', 'run'], { stdio: 'inherit', env: { ...process.env, TMPDIR: temp } });
