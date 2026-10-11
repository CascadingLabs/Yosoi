import { expect, test } from 'vite-plus/test';
import { validateTeachingBlocks } from './teaching.mjs';
const tree = (lang, value) => ({ type: 'root', children: [{ type: 'code', lang, value }] });
test('conceptual steps must be prose rather than copyable pseudo-code', () => {
  expect(() =>
    validateTeachingBlocks(tree('text', 'open a Session\nrun the task'), 'task.md'),
  ).toThrow(/numbered steps/);
  expect(() =>
    validateTeachingBlocks(tree('rust', '// Pseudocode:\nrun_task();'), 'task.md'),
  ).toThrow(/numbered steps/);
  expect(() =>
    validateTeachingBlocks({ type: 'root', children: [{ type: 'list', children: [] }] }, 'task.md'),
  ).not.toThrow();
});
test('real programs and concrete data remain valid teaching blocks', () => {
  expect(() => validateTeachingBlocks(tree('rust', 'fn main() {}'), 'task.md')).not.toThrow();
  expect(() =>
    validateTeachingBlocks(tree('json', '{"format_version":1}'), 'policy.md'),
  ).not.toThrow();
  expect(() =>
    validateTeachingBlocks(tree('python', '# TODO: define the task'), 'task.md'),
  ).toThrow(/unfinished/);
});
