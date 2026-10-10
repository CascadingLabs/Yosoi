import { defineConfig } from 'vite-plus';
export default defineConfig({
  test: {
    include: ['validate.test.mjs', 'navigation.test.mjs', 'bundle.test.mjs'],
    maxWorkers: 1,
    fileParallelism: false,
  },
  fmt: {
    useTabs: false,
    singleQuote: true,
    ignorePatterns: [
      'generate.mjs',
      'generate.test.mjs',
      'reference/**',
      'node_modules/**',
      'bun.lock',
    ],
  },
});
