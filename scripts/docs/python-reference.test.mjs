import { test } from 'vite-plus/test';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

test('Python reference preserves public source declarations without importing the SDK', () => {
  execFileSync(
    'uv',
    [
      'run',
      '--no-project',
      '--python',
      '3.15',
      'python',
      '-m',
      'unittest',
      'discover',
      '-s',
      'scripts/docs/tests',
    ],
    {
      cwd: fileURLToPath(new URL('../..', import.meta.url)),
      stdio: 'inherit',
    },
  );
});
