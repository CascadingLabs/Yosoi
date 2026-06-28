import { readFile, stat } from "node:fs/promises";
import { isAbsolute, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import type { AutocompleteItem } from "@earendil-works/pi-tui";
import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@earendil-works/pi-coding-agent";

const workflows = ["help", "search", "fetch", "crawl", "research"] as const;
const commands = ["help", "search", "fetch", "crawl", "research", "show", "clear", "older", "newer", "latest"] as const;
type Workflow = (typeof workflows)[number];
type YosoiCommand = (typeof commands)[number];

type RunStatus = "running" | "ok" | "error";

interface YosoiRun {
  id: string;
  command: string;
  workflow: string;
  urls: string[];
  startedAt: number;
  endedAt?: number;
  status: RunStatus;
  exitCode?: number;
  httpStatusCodes: number[];
  error?: string;
  outputPath?: string;
  fetcher?: string;
  summary?: string;
  contextTokens?: number;
}

interface UsageLike {
  input?: number;
  output?: number;
  cacheRead?: number;
  cacheWrite?: number;
  totalTokens?: number;
}

const runs: YosoiRun[] = [];
const active = new Map<string, YosoiRun>();
let dashboardVisible = true;
let dashboardScrollOffset = 0;
let latestContextTokens: number | undefined;

const workflowPrompts: Record<Workflow, (target: string) => string> = {
  help: () => `Use the project-local Yosoi web workflows.

Read:
- .agents/skills/yosoi-web-workflows/SKILL.md
- .agents/skills/yosoi-fetch/SKILL.md when fetching page evidence
- .agents/skills/yosoi-research-frontier/SKILL.md when creating a research packet

Summarize the right Yosoi command path for my task. Use uv-run commands only.`,

  search: (target) => `Use Yosoi search for source discovery.

Target/query: ${target || "<fill query>"}

Follow .agents/skills/yosoi-web-workflows/SKILL.md.
Start with:
uvx yosoi search "${target || "QUERY"}" --limit 10 --json > .yosoi/search-results.json

Then inspect candidate URLs, fetch promising pages before making content claims, and report source quality/gaps.`,

  fetch: (target) => `Use Yosoi fetch for bounded page evidence, not scraping.

URL(s): ${target || "<fill URL>"}

Follow .agents/skills/yosoi-web-workflows/SKILL.md and .agents/skills/yosoi-fetch/SKILL.md.
Start with:
uvx yosoi fetch "${target || "URL"}" --view text --chars 12000 --json

If JS/source fidelity matters, compare raw/rendered or save a bundle. Report status, fetcher, truncation, artifacts, and next step.`,

  crawl: (target) => `Use Yosoi crawl for a bounded site/frontier traversal.

Seed(s): ${target || "<fill seed URL>"}

Follow .agents/skills/yosoi-web-workflows/SKILL.md.
Start conservatively:
uvx yosoi crawl "${target || "URL"}" --limit 25 --json > .yosoi/crawl-results.json

Respect policy/robots settings, keep output as artifacts, and fetch/scrape representative pages before claiming structured facts.`,

  research: (target) => `Use the Yosoi research frontier packet workflow.

Topic: ${target || "<fill topic>"}

Follow .agents/skills/yosoi-web-workflows/SKILL.md and .agents/skills/yosoi-research-frontier/SKILL.md.
Start with:
uvx yosoi research init "${target || "TOPIC"}" --json

Then save search/crawl/scrape artifacts into the packet, append observations, and separate available-now evidence from paid/blocked/unknown gaps.`,
};

function truncateToWidth(text: string, width: number, ellipsis = "…"): string {
  if (width <= 0) return "";
  return text.length <= width ? text : text.slice(0, Math.max(0, width - ellipsis.length)) + ellipsis;
}

function terminalLink(label: string, uri: string): string {
  return `\x1b]8;;${uri}\x1b\\${label}\x1b]8;;\x1b\\`;
}

function artifactUri(cwd: string, path: string): string {
  return pathToFileURL(isAbsolute(path) ? path : resolve(cwd, path)).href;
}

function parseArgs(args: string): { command: YosoiCommand; target: string } {
  const trimmed = args.trim();
  if (!trimmed) return { command: "help", target: "" };
  const [first, ...rest] = trimmed.split(/\s+/);
  if ((commands as readonly string[]).includes(first)) {
    return { command: first as YosoiCommand, target: rest.join(" ") };
  }
  return { command: "help", target: trimmed };
}

function completions(prefix: string): AutocompleteItem[] | null {
  const items = commands.map((command) => ({
    value: command,
    label: command,
    detail: command === "show" ? "toggle Yosoi run dashboard" : `Yosoi ${command}`,
  }));
  const filtered = items.filter((item) => item.value.startsWith(prefix.trim()));
  return filtered.length ? filtered : null;
}

function isYosoiShellCommand(command: string): boolean {
  return /(?:^|[\s;&|()])(?:(?:uv\s+run|uvx)\s+)?yosoi\b/.test(command);
}

function extractWorkflow(command: string): string {
  const match = command.match(/(?:^|[\s;&|()])(?:(?:uv\s+run|uvx)\s+)?yosoi\s+([\w-]+)(?:\s+([\w-]+))?/);
  if (!match) return "yosoi";
  return match[1] === "research" && match[2] ? `research ${match[2]}` : match[1];
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function extractUrls(text: string): string[] {
  return unique(text.match(/https?:\/\/[^\s"'<>]+/g) ?? []);
}

function extractRedirectPath(command: string): string | undefined {
  const match = command.match(/(?:^|\s)>\s*([^\s;&|]+)/);
  return match?.[1]?.replace(/^['"]|['"]$/g, "");
}

async function readSmallJsonArtifact(cwd: string, path: string): Promise<unknown | undefined> {
  const resolved = isAbsolute(path) ? path : resolve(cwd, path);
  if (!resolved.includes("/.yosoi/") && !resolved.startsWith("/tmp/")) return undefined;
  try {
    const info = await stat(resolved);
    if (!info.isFile() || info.size > 1_000_000) return undefined;
    return firstJsonObject(await readFile(resolved, "utf8"));
  } catch {
    return undefined;
  }
}

function textFromContent(content: unknown): string {
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => (part && typeof part === "object" && "text" in part ? String((part as { text?: unknown }).text ?? "") : ""))
    .join("\n");
}

function firstJsonObject(text: string): unknown | undefined {
  const trimmed = text.trim();
  for (const candidate of [trimmed, trimmed.slice(trimmed.indexOf("{"), trimmed.lastIndexOf("}") + 1)]) {
    if (!candidate || !candidate.startsWith("{")) continue;
    try {
      return JSON.parse(candidate);
    } catch {
      // keep trying
    }
  }
  return undefined;
}

function getArray(obj: unknown, key: string): unknown[] {
  if (!obj || typeof obj !== "object") return [];
  const value = (obj as Record<string, unknown>)[key];
  return Array.isArray(value) ? value : [];
}

function getRecord(obj: unknown, key: string): Record<string, unknown> | undefined {
  if (!obj || typeof obj !== "object") return undefined;
  const value = (obj as Record<string, unknown>)[key];
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function applyJsonSummary(run: YosoiRun, payload: unknown): void {
  const root = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : undefined;
  if (!root) return;

  const resultUnits = getArray(root, "results");
  const resultUrls: string[] = [];
  for (const raw of resultUnits) {
    if (!raw || typeof raw !== "object") continue;
    const unit = raw as Record<string, unknown>;
    const url = stringValue(unit.final_url) ?? stringValue(unit.url);
    if (url) resultUrls.push(url);
    const code = numberValue(unit.status_code);
    if (code !== undefined) run.httpStatusCodes.push(code);
    run.fetcher ??= stringValue(unit.fetcher_type);
    run.error ??= stringValue(unit.error);
  }
  if (resultUrls.length) run.urls = [...resultUrls, ...run.urls];

  const hits = getArray(root, "hits");
  if (hits.length) {
    for (const raw of hits.slice(0, 5)) {
      if (raw && typeof raw === "object") {
        const url = stringValue((raw as Record<string, unknown>).url);
        if (url) run.urls.push(url);
      }
    }
    run.summary = `${hits.length} search hits`;
  }

  const summary = getRecord(root, "summary");
  if (summary) {
    const fetched = numberValue(summary.pages_fetched);
    const attempted = numberValue(summary.attempted_urls);
    const status = stringValue(summary.status);
    run.summary = [status, fetched !== undefined && attempted !== undefined ? `${fetched}/${attempted} pages` : undefined]
      .filter(Boolean)
      .join(" ");
  }

  const status = stringValue(root.status);
  if (status && !run.summary) run.summary = status;
  run.urls = unique(run.urls);
  run.httpStatusCodes = [...new Set(run.httpStatusCodes)].sort((a, b) => a - b);
}

function latestUsage(ctx: ExtensionContext): UsageLike | undefined {
  const branch = ctx.sessionManager.getBranch();
  for (let index = branch.length - 1; index >= 0; index -= 1) {
    const entry = branch[index];
    if (entry.type !== "message") continue;
    const message = entry.message as { role?: string; usage?: UsageLike; aborted?: boolean; error?: unknown };
    if (message.role !== "assistant" || message.aborted || message.error || !message.usage) continue;
    const total = usageTokens(message.usage);
    if (total > 0) return message.usage;
  }
  return undefined;
}

function usageTokens(usage: UsageLike | undefined): number {
  if (!usage) return 0;
  return usage.totalTokens ?? (usage.input ?? 0) + (usage.output ?? 0) + (usage.cacheRead ?? 0) + (usage.cacheWrite ?? 0);
}

function formatTokens(tokens: number | undefined): string {
  if (tokens === undefined) return "ctx n/a";
  return tokens >= 1000 ? `ctx ${(tokens / 1000).toFixed(1)}k` : `ctx ${tokens}`;
}

function formatDuration(run: YosoiRun): string {
  const end = run.endedAt ?? Date.now();
  return `${((end - run.startedAt) / 1000).toFixed(1)}s`;
}

function statusGlyph(run: YosoiRun): string {
  if (run.status === "running") return "…";
  return run.status === "ok" ? "✓" : "✗";
}

function maxScrollOffset(): number {
  return Math.max(0, runs.length - 6);
}

function clampDashboardScroll(): void {
  dashboardScrollOffset = Math.max(0, Math.min(dashboardScrollOffset, maxScrollOffset()));
}

function runTarget(run: YosoiRun, cwd: string, width: number): string {
  if (run.urls[0]) {
    const label = truncateToWidth(run.urls[0].replace(/^https?:\/\//, ""), width, "…");
    return terminalLink(label, run.urls[0]);
  }
  if (run.outputPath) {
    const label = truncateToWidth(`> ${run.outputPath}`, width, "…");
    return terminalLink(label, artifactUri(cwd, run.outputPath));
  }
  return truncateToWidth("no url", width, "…");
}

function renderRunRow(run: YosoiRun, width: number, cwd: string): string {
  const code = run.httpStatusCodes.length ? run.httpStatusCodes.join(",") : run.exitCode !== undefined ? `exit ${run.exitCode}` : "—";
  const detail = [code, run.fetcher, run.summary, formatDuration(run), formatTokens(run.contextTokens)].filter(Boolean).join(" • ");
  const prefix = `${statusGlyph(run)} ${run.workflow} ${detail} `;
  if (prefix.length >= width) return truncateToWidth(prefix, width, "…");
  return prefix + runTarget(run, cwd, width - prefix.length);
}

function visibleRuns(): YosoiRun[] {
  clampDashboardScroll();
  return runs.slice().reverse().slice(dashboardScrollOffset, dashboardScrollOffset + 6);
}

function dashboardHeader(width: number): string {
  const scroll = dashboardScrollOffset ? ` • offset ${dashboardScrollOffset}/${maxScrollOffset()}` : "";
  return truncateToWidth(`Yosoi runs ${runs.length} • ${formatTokens(latestContextTokens)}${scroll} • /ys show toggles`, width, "…");
}

function renderDashboard(ctx: ExtensionContext): void {
  latestContextTokens = usageTokens(latestUsage(ctx)) || latestContextTokens;
  ctx.ui.setStatus("yosoi", `yosoi ${runs.length}${active.size ? `/${active.size} running` : ""}`);
  if (!dashboardVisible || !ctx.hasUI) {
    ctx.ui.setWidget("yosoi-dashboard", undefined);
    return;
  }

  ctx.ui.setWidget("yosoi-dashboard", (_tui, _theme) => ({
    invalidate() {},
    render(width: number): string[] {
      const rows = visibleRuns().map((run) => renderRunRow(run, width, ctx.cwd));
      return [dashboardHeader(width), ...rows].slice(0, 7);
    },
  }));
}

async function handleYosoiCommand(args: string, ctx: ExtensionCommandContext): Promise<void> {
  const { command, target } = parseArgs(args);
  if (command === "show") {
    dashboardVisible = !dashboardVisible;
    renderDashboard(ctx);
    ctx.ui.notify(`Yosoi dashboard ${dashboardVisible ? "shown" : "hidden"}`, "info");
    return;
  }
  if (command === "clear") {
    runs.length = 0;
    active.clear();
    latestContextTokens = usageTokens(latestUsage(ctx)) || undefined;
    renderDashboard(ctx);
    ctx.ui.notify("Yosoi dashboard cleared", "info");
    return;
  }
  if (command === "older") {
    dashboardScrollOffset += 1;
    clampDashboardScroll();
    dashboardVisible = true;
    renderDashboard(ctx);
    return;
  }
  if (command === "newer") {
    dashboardScrollOffset -= 1;
    clampDashboardScroll();
    dashboardVisible = true;
    renderDashboard(ctx);
    return;
  }
  if (command === "latest") {
    dashboardScrollOffset = 0;
    dashboardVisible = true;
    renderDashboard(ctx);
    return;
  }

  ctx.ui.setEditorText(workflowPrompts[command](target));
  ctx.ui.notify(`Yosoi ${command} workflow prompt loaded`, "info");
}

export default function (pi: ExtensionAPI) {
  const commandOptions = {
    description: "Prefill a Yosoi workflow prompt or toggle the Yosoi run dashboard",
    getArgumentCompletions: completions,
    handler: handleYosoiCommand,
  };
  pi.registerCommand("yosoi", commandOptions);
  pi.registerCommand("ys", commandOptions);

  pi.on("session_start", (_event, ctx) => {
    renderDashboard(ctx);
  });

  pi.on("tool_call", (event, ctx) => {
    if (event.toolName !== "bash") return;
    const command = String((event.input as { command?: unknown }).command ?? "");
    if (!isYosoiShellCommand(command)) return;

    const run: YosoiRun = {
      id: event.toolCallId,
      command,
      workflow: extractWorkflow(command),
      urls: extractUrls(command),
      startedAt: Date.now(),
      status: "running",
      httpStatusCodes: [],
      outputPath: extractRedirectPath(command),
      contextTokens: usageTokens(latestUsage(ctx)) || undefined,
    };
    runs.push(run);
    while (runs.length > 25) runs.shift();
    active.set(event.toolCallId, run);
    renderDashboard(ctx);
  });

  pi.on("tool_result", async (event, ctx) => {
    const run = active.get(event.toolCallId);
    if (!run) return;

    active.delete(event.toolCallId);
    run.endedAt = Date.now();
    run.status = event.isError ? "error" : "ok";
    run.contextTokens = usageTokens(latestUsage(ctx)) || run.contextTokens;

    const output = textFromContent(event.content);
    run.urls = unique([...run.urls, ...extractUrls(output)]);
    const exit = output.match(/Command exited with code (\d+)/);
    if (exit) run.exitCode = Number(exit[1]);
    if (event.isError) run.error = output.split("\n").slice(-2).join(" ").trim() || "command failed";

    const payload = firstJsonObject(output) ?? (run.outputPath ? await readSmallJsonArtifact(ctx.cwd, run.outputPath) : undefined);
    if (payload) applyJsonSummary(run, payload);
    renderDashboard(ctx);
  });

  pi.on("agent_end", (_event, ctx) => {
    latestContextTokens = usageTokens(latestUsage(ctx)) || latestContextTokens;
    renderDashboard(ctx);
  });
}
