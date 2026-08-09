#!/usr/bin/env node
/** Opt-in Luna 5.6 evaluation over the frozen, safe QA-action fixture. */

import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const sdkRoot = process.env.PI_SDK_ROOT;
if (!sdkRoot) throw new Error('PI_SDK_ROOT must point to the installed @earendil-works/pi-coding-agent package');
const sdk = await import(pathToFileURL(join(sdkRoot, 'dist/index.js')).href);
const requireFromSdk = createRequire(join(sdkRoot, 'package.json'));
const { Type } = requireFromSdk('typebox');
const { createAgentSession, defineTool, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager } = sdk;

const fixturePath = join(ROOT, 'tests/fixtures/qa_discovery/imdb_like/session.json');
const skillPath = join(ROOT, 'yosoi/agent_assets/skills/yosoi-qa-action/SKILL.md');
const fixture = JSON.parse(await readFile(fixturePath, 'utf8'));
const skill = await readFile(skillPath, 'utf8');
const outputPath = process.env.YOSOI_LUNA_RESULT || join(ROOT, 'data/evals/cas273-luna-discovery.json');

let position = 0;
let statusChecked = false;
let overviewSnapshot = null;
let completed = false;
let toolCalls = 0;
let actionCount = 0;
const audit = [];
const decisions = [];
const maxToolCalls = 16;
const maxActions = 3;

function state() { return fixture.states[position]; }
function exactNode(role, name, nodes = state().nodes) {
  return nodes.filter((node) => node.role === role && node.name === name);
}
function toolGuard(name) {
  toolCalls += 1;
  if (toolCalls > maxToolCalls) throw new Error('tool_budget_exhausted');
  if (completed) throw new Error('session_already_completed');
  audit.push({ event: 'tool', name, snapshot_id: state().snapshot_id });
}
function receipt(kind, target, expect) {
  const before = state().snapshot_id;
  const next = fixture.states[position + 1];
  if (!next) throw new Error('no_fixture_transition');
  if (expect.url === undefined) {
    const matches = exactNode(expect.role, expect.name, next.nodes);
    if (matches.length !== 1) throw new Error(matches.length ? 'postcondition_ambiguous' : 'postcondition_missing');
  }
  position += 1;
  overviewSnapshot = null;
  actionCount += 1;
  const payload = { kind, before, after: next.snapshot_id, target, expect, outcome: 'success' };
  const fingerprint = createHash('sha256').update(JSON.stringify(payload)).digest('hex');
  const result = { ...payload, assertion_status: 'passed', receipt_fingerprint: fingerprint };
  audit.push({ event: 'receipt', ...result });
  return result;
}
function result(value) {
  return { content: [{ type: 'text', text: JSON.stringify(value) }], details: value };
}

const tools = [
  defineTool({
    name: 'qa_status', label: 'QA status', description: 'Check bounded fixture-session capabilities before any observation or action.',
    parameters: Type.Object({}, { additionalProperties: false }),
    execute: async () => {
      toolGuard('qa_status'); statusChecked = true;
      return result({ ready: true, snapshot_id: state().snapshot_id, capabilities: { index: true, capture: true, actions: true, deterministic_assertions: true, a3_recording: true }, safe_navigation_url: fixture.safe_navigation_url, limits: { max_tool_calls: maxToolCalls, max_actions: maxActions } });
    },
  }),
  defineTool({
    name: 'qa_overview', label: 'QA overview', description: 'Render the current model-safe indexed AX overview with snapshot-local ordinals.',
    parameters: Type.Object({}, { additionalProperties: false }),
    execute: async () => {
      toolGuard('qa_overview');
      if (!statusChecked) throw new Error('status_required');
      overviewSnapshot = state().snapshot_id;
      return result({ snapshot_id: state().snapshot_id, entries: state().nodes.map((node, ordinal) => ({ ordinal, role: node.role, name: node.name })) });
    },
  }),
  defineTool({
    name: 'qa_navigate', label: 'QA navigate', description: 'Navigate once to the controller-declared exact safe HTTPS URL; the controller verifies URL identity and a real after-capture.',
    parameters: Type.Object({ url: Type.String({ minLength: 1, maxLength: 2048 }) }, { additionalProperties: false }),
    execute: async (_id, params) => {
      toolGuard('qa_navigate');
      audit.push({ event: 'decision', name: 'qa_navigate', params });
      if (overviewSnapshot !== state().snapshot_id) throw new Error('current_overview_required');
      if (position !== 0 || actionCount !== 0) throw new Error('navigation_only_allowed_as_initial_setup');
      if (actionCount >= maxActions) throw new Error('action_budget_exhausted');
      const url = new URL(params.url);
      if (params.url !== fixture.safe_navigation_url || url.protocol !== 'https:' || url.hostname !== 'www.imdb.com' || url.username || url.password || url.hash) throw new Error('unsafe_navigation');
      decisions.push({ decision: 'navigate', url: params.url });
      return result(receipt('navigate', null, { url: fixture.safe_navigation_url }));
    },
  }),
  defineTool({
    name: 'qa_click', label: 'QA click', description: 'Click one actionable AX ordinal from the current snapshot and require an exact AX postcondition.',
    parameters: Type.Object({ snapshot_id: Type.String({ minLength: 1, maxLength: 256 }), ordinal: Type.Integer({ minimum: 0 }), expected_role: Type.String({ minLength: 1, maxLength: 64 }), expected_name: Type.String({ minLength: 1, maxLength: 512 }) }, { additionalProperties: false }),
    execute: async (_id, params) => {
      toolGuard('qa_click');
      audit.push({ event: 'decision', name: 'qa_click', params });
      if (params.snapshot_id !== state().snapshot_id || overviewSnapshot !== state().snapshot_id) throw new Error('stale_or_unseen_target');
      if (actionCount >= maxActions) throw new Error('action_budget_exhausted');
      const target = state().nodes[params.ordinal];
      if (!target || !['link', 'button', 'tab'].includes(target.role)) throw new Error('target_unbindable');
      const assertionId = position === 1 ? 'film-heading' : 'person-heading';
      decisions.push({ decision: 'click', snapshot_id: params.snapshot_id, ordinal: params.ordinal, expect: { assertion_id: assertionId, semantic_role: params.expected_role, accessible_name: params.expected_name } });
      return result(receipt('click', { snapshot_id: state().snapshot_id, ordinal: params.ordinal, role: target.role, name_sha256: createHash('sha256').update(target.name).digest('hex') }, { role: params.expected_role, name: params.expected_name }));
    },
  }),
  defineTool({
    name: 'qa_complete', label: 'QA complete', description: 'Complete only when the final indexed state proves the goal and declared fields.',
    parameters: Type.Object({}, { additionalProperties: false }),
    execute: async () => {
      toolGuard('qa_complete');
      if (position !== fixture.states.length - 1 || overviewSnapshot !== state().snapshot_id) throw new Error('goal_not_proven');
      for (const [field, expected] of Object.entries(fixture.declared_fields)) {
        const values = Array.isArray(expected) ? expected : [expected];
        if (!values.every((value) => state().nodes.some((node) => node.name === value))) throw new Error(`declared_field_missing:${field}`);
      }
      completed = true;
      const value = { status: 'completed', snapshot_id: state().snapshot_id, declared_fields: fixture.declared_fields, action_count: actionCount, tool_calls: toolCalls };
      audit.push({ event: 'complete', ...value });
      return result(value);
    },
  }),
];

const modelRuntime = await ModelRuntime.create();
const model = modelRuntime.getModel('openai-codex', 'gpt-5.6-luna');
if (!model) throw new Error('openai-codex/gpt-5.6-luna is unavailable');
const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: true, maxRetries: 1 } });
const agentDir = sdk.getAgentDir();
const loader = new DefaultResourceLoader({ cwd: ROOT, agentDir, settingsManager, noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, systemPrompt: `You are Luna, a bounded QA discovery agent.\n\n${skill}` });
await loader.reload();
const { session } = await createAgentSession({ cwd: ROOT, agentDir, model, modelRuntime, thinkingLevel: 'high', tools: tools.map((tool) => tool.name), customTools: tools, resourceLoader: loader, sessionManager: SessionManager.inMemory(ROOT), settingsManager });
let modelTurns = 0;
session.subscribe((event) => { if (event.type === 'turn_end') modelTurns += 1; });
try {
  await session.prompt(`Discover this goal using only qa_* tools: ${fixture.goal}. Start with qa_status. Stop on any refusal or drift. Call qa_complete only after the final indexed state proves all declared fields.`);
} finally {
  session.dispose();
}
const final = { schema_version: 'cas273-luna-eval1', model: 'openai-codex/gpt-5.6-luna', fixture: fixture.fixture_version, completed, final_snapshot_id: state().snapshot_id, action_count: actionCount, tool_calls: toolCalls, model_turns: modelTurns, decisions, audit };
await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(final, null, 2)}\n`);
console.log(JSON.stringify(final));
if (!completed) process.exitCode = 1;
