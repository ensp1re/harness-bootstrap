#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { execFile as execFileCallback, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { promises as fs } from 'node:fs';
import path from 'node:path';

const execFile = promisify(execFileCallback);
const SCHEMA_VERSION = 1;
const HARNESS = 'docs/harness';
const STATE_FILES = {
  config: `${HARNESS}/config.json`,
  tasks: `${HARNESS}/tasks.json`,
  handoff: `${HARNESS}/handoff.json`,
  install: `${HARNESS}/install.json`,
};
const GENERATED = {
  [`${HARNESS}/AGENTS.md`]: `# Harness router\n\nRead the repository root AGENTS.md first. Harness state lives in this directory.\n\n- Run \`node scripts/harness-runner.mjs --root . context\` for current state.\n- Run \`node scripts/harness-runner.mjs --root . tasks\` for ready work.\n- Run \`node scripts/harness-runner.mjs --root . validate\` before relying on evidence.\n- Product implementation is queued in tasks.json; harness bootstrap does not implement it.\n`,
  [`${HARNESS}/PROJECT.md`]: `# JSON formatter CLI\n\n## Outcome\n\nProvide a local Node CLI that reads one JSON value from stdin and writes normalized JSON to stdout.\n\n## Constraints\n\n- Preserve the existing package scripts and repository instructions.\n- Use two-space indentation and a trailing newline.\n- Keep the implementation local and dependency-free.\n\n## Acceptance\n\n- Valid JSON is formatted deterministically.\n- Invalid JSON exits non-zero with a useful diagnostic.\n- The existing test script remains runnable.\n`,
  [`${HARNESS}/PLAN.md`]: `# Harness plan\n\n## Current task\n\nF001: Implement the local JSON formatter CLI.\n\n## Next steps\n\n1. Activate F001.\n2. Implement the formatter and its CLI boundary.\n3. Run the configured unit and formatter acceptance checks.\n4. Record a fresh handoff and delivery evidence.\n`,
  [`${HARNESS}/SESSION_HANDOFF.md`]: `# Session handoff\n\nThe formatter implementation is queued as F001. The bootstrap has generated a native runner and initial verification configuration.\n\nNext action: activate F001, then implement the formatter.\n`,
  [`${HARNESS}/RELIABILITY.md`]: `# Reliability contract\n\nVerification writes a started attempt before running checks, retains every outcome, fingerprints configured inputs before and after checks, and refuses stale evidence. Interrupted or missing checks cannot pass.\n`,
  'tests/formatter.acceptance.mjs': `import assert from 'node:assert/strict';\nimport { formatJson } from '../src/format-json.mjs';\n\nassert.equal(formatJson({ b: 1, a: [true, null] }), '{\\n  "b": 1,\\n  "a": [\\n    true,\\n    null\\n  ]\\n}\\n');\nlet invalid = false;\ntry { formatJson('{broken'); } catch { invalid = true; }\nassert.equal(invalid, true);\nconsole.log('formatter acceptance passed');\n`,
};

class HarnessError extends Error {
  constructor(message, exitCode = 2, details = undefined) {
    super(message);
    this.name = 'HarnessError';
    this.exitCode = exitCode;
    this.details = details;
  }
}

function json(value) {
  return `${JSON.stringify(value)}\n`;
}

function emit(value, exitCode = 0) {
  process.stdout.write(json(value));
  process.exitCode = exitCode;
}

function parseCli(argv) {
  if (argv[0] !== '--root' || !argv[1] || !argv[2]) {
    throw new HarnessError('usage: harness-runner --root PATH COMMAND [arguments]', 2);
  }
  const root = path.resolve(argv[1]);
  const command = argv[2];
  const rest = argv.slice(3);
  return { root, command, rest };
}

async function exists(file) {
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

async function statOrNull(file) {
  try {
    return await fs.lstat(file);
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}

async function realRoot(root) {
  const stat = await fs.stat(root).catch(() => null);
  if (!stat?.isDirectory()) throw new HarnessError(`root is not a directory: ${root}`);
  return fs.realpath(root);
}

function relativeStoredPath(value) {
  if (typeof value !== 'string' || value.length === 0 || path.isAbsolute(value)) {
    throw new HarnessError(`path must be a non-empty relative path: ${String(value)}`, 2);
  }
  const normalized = path.normalize(value);
  if (normalized === '..' || normalized.startsWith(`..${path.sep}`)) {
    throw new HarnessError(`path escapes root: ${value}`, 2);
  }
  return normalized;
}

async function safePath(root, stored, { allowMissing = true } = {}) {
  const relative = relativeStoredPath(stored);
  const candidate = path.resolve(root, relative);
  const rootPrefix = `${root}${path.sep}`;
  if (candidate !== root && !candidate.startsWith(rootPrefix)) {
    throw new HarnessError(`path escapes root: ${stored}`, 2);
  }
  let probe = candidate;
  while (true) {
    const stat = await statOrNull(probe);
    if (stat) break;
    if (probe === root) break;
    probe = path.dirname(probe);
  }
  const resolvedProbe = await fs.realpath(probe);
  if (resolvedProbe !== root && !resolvedProbe.startsWith(rootPrefix)) {
    throw new HarnessError(`symlink escapes root: ${stored}`, 2);
  }
  if (!allowMissing && !(await exists(candidate))) {
    throw new HarnessError(`missing path: ${stored}`, 2);
  }
  return candidate;
}

async function readJson(root, stored, { allowMissing = false } = {}) {
  const file = await safePath(root, stored, { allowMissing });
  if (!(await exists(file))) return null;
  let text;
  try {
    text = await fs.readFile(file, 'utf8');
  } catch (error) {
    throw new HarnessError(`cannot read ${stored}: ${error.message}`, 2);
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new HarnessError(`malformed JSON in ${stored}: ${error.message}`, 1);
  }
}

async function atomicWrite(root, stored, value) {
  const file = await safePath(root, stored);
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.tmp-${process.pid}-${Date.now()}`;
  await fs.writeFile(temporary, typeof value === 'string' ? value : json(value), 'utf8');
  await fs.rename(temporary, file);
}

async function sha256Buffer(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

async function sha256File(file) {
  return sha256Buffer(await fs.readFile(file));
}

async function walkFiles(root, stored) {
  const file = await safePath(root, stored, { allowMissing: true });
  const stat = await statOrNull(file);
  if (!stat) throw new HarnessError(`fingerprint input is missing: ${stored}`, 1);
  if (stat.isSymbolicLink()) {
    await safePath(root, stored, { allowMissing: false });
    const target = await fs.realpath(file);
    const rootPrefix = `${root}${path.sep}`;
    if (target !== root && !target.startsWith(rootPrefix)) {
      throw new HarnessError(`fingerprint symlink escapes root: ${stored}`, 1);
    }
    return [{ path: stored, sha256: await sha256File(file) }];
  }
  if (stat.isFile()) return [{ path: stored, sha256: await sha256File(file) }];
  if (!stat.isDirectory()) throw new HarnessError(`unsupported fingerprint input: ${stored}`, 1);
  const names = (await fs.readdir(file)).sort();
  const records = [];
  for (const name of names) {
    const child = path.join(stored, name);
    if (child === `${HARNESS}/runs` || child.startsWith(`${HARNESS}/runs${path.sep}`) ||
        child === `${HARNESS}/archive` || child.startsWith(`${HARNESS}/archive${path.sep}`)) continue;
    records.push(...await walkFiles(root, child));
  }
  return records;
}

async function fingerprint(root, paths) {
  const records = [];
  for (const stored of paths) records.push(...await walkFiles(root, stored));
  records.sort((a, b) => a.path.localeCompare(b.path));
  const digest = createHash('sha256');
  for (const record of records) digest.update(`${record.path}\0${record.sha256}\n`);
  const config = await readJson(root, `${HARNESS}/config.json`);
  const state = await readJson(root, `${HARNESS}/tasks.json`);
  digest.update(JSON.stringify(config));
  digest.update(JSON.stringify(state.tasks.map(({ id, behavior, acceptance, spec, plan, verification }) => ({ id, behavior, acceptance, spec, plan, verification }))));
  return { digest: digest.digest('hex'), files: records };
}

async function acquireLock(root) {
  const lockStored = `${HARNESS}/state.lock`;
  const lock = await safePath(root, lockStored);
  await fs.mkdir(path.dirname(lock), { recursive: true });
  try {
    const handle = await fs.open(lock, 'wx');
    await handle.writeFile(json({ pid: process.pid, startedAt: new Date().toISOString() }));
    await handle.close();
  } catch (error) {
    if (error.code === 'EEXIST') throw new HarnessError('harness state is locked by another writer', 1);
    throw error;
  }
  return async () => fs.unlink(lock).catch(() => {});
}

async function loadState(root) {
  const config = await readJson(root, STATE_FILES.config);
  const tasks = await readJson(root, STATE_FILES.tasks);
  const handoff = await readJson(root, STATE_FILES.handoff, { allowMissing: true });
  if (!config || !tasks) throw new HarnessError('harness is not initialized; run init first', 2);
  return { config, tasks, handoff };
}

function taskById(tasks, id) {
  return tasks.tasks.find((task) => task.id === id);
}

async function archivedTasks(root) {
  const directory = await safePath(root, `${HARNESS}/archive`);
  if (!(await exists(directory))) return [];
  const names = (await fs.readdir(directory)).filter((name) => name.endsWith('.json')).sort();
  const result = [];
  for (const name of names) {
    const stored = `${HARNESS}/archive/${name}`;
    const value = await readJson(root, stored);
    if (value?.task?.id) result.push(value.task);
  }
  return result;
}

function checkMap(config) {
  return new Map((config.checks ?? []).map((check) => [check.id, check]));
}

function detectCycles(tasks, archived) {
  const all = new Map([...tasks, ...archived].map((task) => [task.id, task]));
  const visiting = new Set();
  const visited = new Set();
  const cycles = [];
  function visit(id, stack = []) {
    if (visiting.has(id)) {
      const index = stack.indexOf(id);
      cycles.push([...stack.slice(index), id].join(' -> '));
      return;
    }
    if (visited.has(id)) return;
    visiting.add(id);
    const task = all.get(id);
    for (const dependency of task?.dependsOn ?? []) visit(dependency, [...stack, id]);
    visiting.delete(id);
    visited.add(id);
  }
  for (const task of tasks) visit(task.id);
  return cycles;
}

function validateConfig(config) {
  const errors = [];
  if (config?.schemaVersion !== SCHEMA_VERSION) errors.push('config schemaVersion must be 1');
  if (!Array.isArray(config?.checks)) errors.push('config checks must be an array');
  const ids = new Set();
  for (const check of config?.checks ?? []) {
    if (!check || typeof check !== 'object') { errors.push('check must be an object'); continue; }
    if (typeof check.id !== 'string' || !check.id) errors.push('check id must be non-empty');
    if (ids.has(check.id)) errors.push(`duplicate check id: ${check.id}`);
    ids.add(check.id);
    if (!Array.isArray(check.argv) || check.argv.length === 0 || check.argv.some((part) => typeof part !== 'string' || !part)) {
      errors.push(`check ${check.id} argv must be a non-empty argv array`);
    }
    if (typeof check.cwd !== 'string' || path.isAbsolute(check.cwd) || check.cwd.includes('..')) errors.push(`check ${check.id} cwd must be relative`);
    if (typeof check.timeoutSeconds !== 'number' || check.timeoutSeconds <= 0) errors.push(`check ${check.id} timeoutSeconds must be positive`);
    if (typeof check.required !== 'boolean') errors.push(`check ${check.id} required must be boolean`);
  }
  if (!Array.isArray(config?.fingerprintPaths) || config.fingerprintPaths.length === 0) errors.push('config fingerprintPaths must be non-empty');
  if (config?.delivery && typeof config.delivery !== 'object') errors.push('config delivery must be an object');
  return errors;
}

async function validateState(root, state, { includeFreshness = true } = {}) {
  const { config, tasks, handoff } = state;
  const errors = [...validateConfig(config)];
  const warnings = [];
  const archived = await archivedTasks(root).catch(() => []);
  const allIds = new Set();
  let maxNumericId = 0;
  let activeCount = 0;
  const validStates = new Set(['not_started', 'active', 'blocked', 'verified', 'passing']);
  if (tasks?.schemaVersion !== SCHEMA_VERSION) errors.push('tasks schemaVersion must be 1');
  if (!Array.isArray(tasks?.tasks)) errors.push('tasks tasks must be an array');
  for (const task of tasks?.tasks ?? []) {
    if (!task || typeof task !== 'object') { errors.push('task must be an object'); continue; }
    if (!/^F\d{3,}$/.test(task.id ?? '')) errors.push(`invalid task id: ${task.id}`);
    if (allIds.has(task.id)) errors.push(`duplicate task id: ${task.id}`);
    allIds.add(task.id);
    maxNumericId = Math.max(maxNumericId, Number(String(task.id).slice(1)) || 0);
    if (typeof task.behavior !== 'string' || !task.behavior.trim()) errors.push(`${task.id} behavior is required`);
    if (!Array.isArray(task.acceptance) || task.acceptance.length === 0 || task.acceptance.some((item) => typeof item !== 'string' || !item.trim())) errors.push(`${task.id} acceptance must be non-empty`);
    if (!Array.isArray(task.dependsOn)) errors.push(`${task.id} dependsOn must be an array`);
    if (!validStates.has(task.state)) errors.push(`${task.id} has invalid state ${task.state}`);
    if (task.state === 'active') activeCount += 1;
    if (task.state === 'blocked' && (!task.blockedReason || typeof task.blockedReason !== 'string')) errors.push(`${task.id} blocked state requires blockedReason`);
    if (task.spec !== null && task.spec !== undefined && (typeof task.spec !== 'string' || path.isAbsolute(task.spec))) errors.push(`${task.id} spec must be relative or null`);
    if (task.plan !== null && task.plan !== undefined && (typeof task.plan !== 'string' || path.isAbsolute(task.plan))) errors.push(`${task.id} plan must be relative or null`);
    if (!Array.isArray(task.verification)) errors.push(`${task.id} verification must be an array`);
    for (const checkId of task.verification ?? []) if (!checkMap(config).has(checkId)) errors.push(`${task.id} references unknown check ${checkId}`);
    if (task.evidence !== null && task.evidence !== undefined && typeof task.evidence !== 'object') errors.push(`${task.id} evidence must be an object or null`);
    if (task.state === 'verified' || task.state === 'passing') {
      if (task.evidence?.status !== 'passed') errors.push(`${task.id} ${task.state} requires passed evidence`);
      if (!task.evidence?.attemptId) errors.push(`${task.id} ${task.state} requires an attemptId`);
      if (includeFreshness && task.evidence?.status === 'passed') {
        try {
          const current = await fingerprint(root, config.fingerprintPaths);
          const expected = task.evidence.fingerprintAfter ?? task.evidence.fingerprintBefore;
          if (current.digest !== expected) {
            const message = `${task.id} evidence is stale`;
            errors.push(message);
          }
        } catch (error) {
          errors.push(`${task.id} freshness unavailable: ${error.message}`);
        }
      }
    }
  }
  for (const task of archived) {
    if (allIds.has(task.id)) errors.push(`duplicate live/archive task id: ${task.id}`);
    allIds.add(task.id);
    maxNumericId = Math.max(maxNumericId, Number(String(task.id).slice(1)) || 0);
  }
  if (!Number.isInteger(tasks?.nextId) || tasks.nextId <= maxNumericId) errors.push('tasks nextId must exceed every allocated numeric id');
  if (activeCount > 1) errors.push('at most one task may be active');
  const liveIds = new Set((tasks?.tasks ?? []).map((task) => task.id));
  const archivedIds = new Set(archived.map((task) => task.id));
  for (const task of tasks?.tasks ?? []) {
    for (const dependency of task.dependsOn ?? []) {
      if (!liveIds.has(dependency) && !archivedIds.has(dependency)) errors.push(`${task.id} depends on missing task ${dependency}`);
    }
  }
  errors.push(...detectCycles(tasks?.tasks ?? [], archived).map((cycle) => `dependency cycle: ${cycle}`));
  for (const task of tasks?.tasks ?? []) {
    for (const stored of [task.spec, task.plan]) {
      if (stored && !(await exists(await safePath(root, stored)))) errors.push(`${task.id} references missing artifact ${stored}`);
    }
  }
  if (handoff?.activeTask !== null && handoff?.activeTask !== undefined && !allIds.has(handoff.activeTask)) errors.push(`handoff references missing task ${handoff.activeTask}`);
  return { errors, warnings, archived };
}

function defaultConfig() {
  return {
    schemaVersion: SCHEMA_VERSION,
    checks: [
      { id: 'unit', argv: ['npm', 'test'], cwd: '.', timeoutSeconds: 30, required: true },
      { id: 'formatter', argv: ['node', 'tests/formatter.acceptance.mjs'], cwd: '.', timeoutSeconds: 30, required: true },
      { id: 'lint', argv: ['npm', 'run', 'lint'], cwd: '.', timeoutSeconds: 30, required: false },
    ],
    fingerprintPaths: ['src', 'tests', 'package.json', 'AGENTS.md', `${HARNESS}/PROJECT.md`, `${HARNESS}/PLAN.md`],
    delivery: { provider: 'github', defaultBranch: 'main', requirePR: true },
  };
}

function defaultTasks() {
  return {
    schemaVersion: SCHEMA_VERSION,
    nextId: 2,
    tasks: [{
      id: 'F001',
      behavior: 'Implement a local JSON formatter CLI that reads JSON and emits deterministic normalized JSON.',
      acceptance: [
        'Valid JSON is formatted with two-space indentation and a trailing newline.',
        'Invalid JSON exits non-zero with a useful diagnostic.',
        'The existing package test script remains runnable.',
      ],
      dependsOn: [],
      state: 'not_started',
      spec: `${HARNESS}/PROJECT.md`,
      plan: `${HARNESS}/PLAN.md`,
      verification: ['unit', 'formatter'],
      blockedReason: null,
      evidence: null,
      delivery: null,
    }],
  };
}

function defaultHandoff() {
  return {
    schemaVersion: SCHEMA_VERSION,
    objective: 'Implement the local JSON formatter CLI.',
    activeTask: null,
    git: null,
    evidence: null,
    decisions: [],
    rejectedApproaches: [],
    blockers: [],
    nextAction: 'Activate F001, then implement the formatter.',
    updatedAt: new Date().toISOString(),
  };
}

async function init(root) {
  await fs.mkdir(await safePath(root, HARNESS), { recursive: true });
  await fs.mkdir(await safePath(root, `${HARNESS}/runs`), { recursive: true });
  await fs.mkdir(await safePath(root, `${HARNESS}/archive`), { recursive: true });
  const install = await readJson(root, STATE_FILES.install, { allowMissing: true });
  const previousFiles = new Map((install?.files ?? []).map((item) => [item.path, item]));
  const created = [];
  const conflicts = [];
  const preserved = [];
  const generatedRecords = [];
  for (const [stored, content] of Object.entries(GENERATED)) {
    const file = await safePath(root, stored);
    const current = await statOrNull(file);
    if (!current) {
      await atomicWrite(root, stored, content);
      created.push(stored);
    } else {
      const actualHash = await sha256File(file);
      const expected = previousFiles.get(stored)?.sha256;
      if (expected && actualHash !== expected) {
        conflicts.push({ path: stored, expectedSha256: expected, actualSha256: actualHash });
        preserved.push(stored);
      } else if (!expected) {
        preserved.push(stored);
      }
    }
    const afterHash = await sha256File(file);
    generatedRecords.push({ path: stored, sha256: previousFiles.get(stored)?.sha256 ?? afterHash });
  }
  const existingConfig = await readJson(root, STATE_FILES.config, { allowMissing: true });
  if (!existingConfig) { await atomicWrite(root, STATE_FILES.config, defaultConfig()); created.push(STATE_FILES.config); }
  const existingTasks = await readJson(root, STATE_FILES.tasks, { allowMissing: true });
  if (!existingTasks) { await atomicWrite(root, STATE_FILES.tasks, defaultTasks()); created.push(STATE_FILES.tasks); }
  const existingHandoff = await readJson(root, STATE_FILES.handoff, { allowMissing: true });
  if (!existingHandoff) { await atomicWrite(root, STATE_FILES.handoff, defaultHandoff()); created.push(STATE_FILES.handoff); }
  const manifest = {
    schemaVersion: SCHEMA_VERSION,
    generatedBy: 'harness-bootstrap forward evaluation',
    generatedAt: install?.generatedAt ?? new Date().toISOString(),
    files: generatedRecords,
    preserved,
    conflicts,
    untouched: ['package.json', 'AGENTS.md'],
  };
  await atomicWrite(root, STATE_FILES.install, manifest);
  return { ok: true, command: 'init', created, preserved, conflicts, untouched: manifest.untouched, queued: ['F001'] };
}

async function gitInfo(root) {
  try {
    const [branch, revision, status] = await Promise.all([
      execFile('git', ['-C', root, 'branch', '--show-current']),
      execFile('git', ['-C', root, 'rev-parse', 'HEAD']),
      execFile('git', ['-C', root, 'status', '--porcelain']),
    ]);
    return {
      available: true,
      branch: branch.stdout.trim() || null,
      revision: revision.stdout.trim() || null,
      dirty: Boolean(status.stdout.trim()),
    };
  } catch {
    return { available: false, branch: null, revision: null, dirty: null };
  }
}

function readyTasks(tasks) {
  const passing = new Set(tasks.tasks.filter((task) => task.state === 'passing').map((task) => task.id));
  return tasks.tasks
    .filter((task) => task.state === 'not_started' && (task.dependsOn ?? []).every((id) => passing.has(id)))
    .sort((a, b) => Number(a.id.slice(1)) - Number(b.id.slice(1)))
    .map((task) => task.id);
}

async function commandContext(root) {
  const state = await loadState(root);
  const validation = await validateState(root, state);
  const freshness = {};
  for (const task of state.tasks.tasks) {
    if (task.evidence?.status === 'passed') {
      try {
        const current = await fingerprint(root, state.config.fingerprintPaths);
        freshness[task.id] = {
          fresh: current.digest === (task.evidence.fingerprintAfter ?? task.evidence.fingerprintBefore),
          digest: current.digest,
          expected: task.evidence.fingerprintAfter ?? task.evidence.fingerprintBefore,
        };
      } catch (error) {
        freshness[task.id] = { fresh: false, reason: error.message };
      }
    }
  }
  const active = state.tasks.tasks.find((task) => task.state === 'active') ?? null;
  emit({
    ok: validation.errors.length === 0,
    schemaVersion: SCHEMA_VERSION,
    git: await gitInfo(root),
    activeTask: active?.id ?? null,
    readyTaskIds: readyTasks(state.tasks),
    blockers: state.tasks.tasks.filter((task) => task.state === 'blocked').map((task) => ({ id: task.id, reason: task.blockedReason })),
    evidenceFreshness: freshness,
    nextAction: state.handoff?.nextAction ?? null,
    warnings: validation.warnings,
    errors: validation.errors,
  }, validation.errors.length ? 1 : 0);
}

async function commandTasks(root) {
  const state = await loadState(root);
  const validation = await validateState(root, state, { includeFreshness: false });
  emit({ ok: validation.errors.length === 0, tasks: state.tasks.tasks, readyTaskIds: readyTasks(state.tasks), warnings: validation.warnings, errors: validation.errors }, validation.errors.length ? 1 : 0);
}

async function commandValidate(root) {
  try {
    const state = await loadState(root);
    const validation = await validateState(root, state);
    emit({ ok: validation.errors.length === 0, errors: validation.errors, warnings: validation.warnings }, validation.errors.length ? 1 : 0);
  } catch (error) {
    const code = error instanceof HarnessError ? error.exitCode : 2;
    emit({ ok: false, errors: [error.message] }, code);
  }
}

function parseReason(args) {
  const index = args.indexOf('--reason');
  if (index === -1) return null;
  return args[index + 1] || null;
}

async function commandTransition(root, args) {
  const id = args[0];
  const target = args[1];
  if (!id || !target) throw new HarnessError('usage: transition ID STATE', 2);
  const release = await acquireLock(root);
  try {
    const state = await loadState(root);
    const validation = await validateState(root, state, { includeFreshness: false });
    if (validation.errors.length) throw new HarnessError('state is invalid; transition refused', 1, validation.errors);
    const task = taskById(state.tasks, id);
    if (!task) throw new HarnessError(`unknown live task: ${id}`, 2);
    if (target === 'active') {
      if (!['not_started', 'blocked', 'verified'].includes(task.state)) throw new HarnessError(`${id} cannot transition ${task.state} -> active`, 1);
      if (task.state !== 'verified' && state.tasks.tasks.some((item) => item.state === 'active')) throw new HarnessError('WIP limit reached: another task is active', 1);
      const passing = new Set(state.tasks.tasks.filter((item) => item.state === 'passing').map((item) => item.id));
      if (!(task.dependsOn ?? []).every((dependency) => passing.has(dependency))) throw new HarnessError(`${id} has unsatisfied dependencies`, 1);
      task.state = 'active';
      task.blockedReason = null;
    } else if (target === 'blocked') {
      if (task.state !== 'active') throw new HarnessError(`${id} can only become blocked from active`, 1);
      const reason = parseReason(args);
      if (!reason) throw new HarnessError('blocked transition requires --reason TEXT', 2);
      task.state = 'blocked';
      task.blockedReason = reason;
    } else if (target === 'verified') {
      throw new HarnessError('verified is produced only by verify ID', 1);
    } else if (target === 'passing') {
      if (task.state !== 'verified') throw new HarnessError(`${id} can only become passing from verified`, 1);
      const freshness = task.evidence?.status === 'passed' ? await fingerprint(root, state.config.fingerprintPaths) : null;
      if (!freshness || freshness.digest !== (task.evidence.fingerprintAfter ?? task.evidence.fingerprintBefore)) throw new HarnessError(`${id} evidence is stale`, 1);
      if (!task.delivery?.implementationRevision || task.delivery?.ciStatus !== 'passed') throw new HarnessError(`${id} requires implementationRevision and ciStatus=passed`, 1);
      task.state = 'passing';
    } else {
      throw new HarnessError(`unsupported transition target: ${target}`, 2);
    }
    await atomicWrite(root, STATE_FILES.tasks, state.tasks);
    emit({ ok: true, command: 'transition', id, state: task.state });
  } finally {
    await release();
  }
}

function commandString(check) {
  return [check.argv[0], ...check.argv.slice(1)].map((item) => JSON.stringify(item)).join(' ');
}

async function runCheck(root, check, logFile) {
  const cwd = await safePath(root, check.cwd ?? '.');
  const started = Date.now();
  return new Promise((resolve) => {
    let child;
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      resolve({
        ...result,
        argv: check.argv,
        cwd: check.cwd ?? '.',
        durationMs: Date.now() - started,
        logPath: logFile,
        stdout,
        stderr,
      });
    };
    try {
      child = spawn(check.argv[0], check.argv.slice(1), {
        cwd,
        env: process.env,
        stdio: ['ignore', 'pipe', 'pipe'],
        detached: true,
      });
    } catch (error) {
      finish({ status: error.code === 'ENOENT' ? 'missing_executable' : 'failed', error: error.message, exitCode: null, signal: null });
      return;
    }
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    const timeout = setTimeout(() => {
      timedOut = true;
      try { process.kill(-child.pid, 'SIGTERM'); } catch { child.kill('SIGTERM'); }
      setTimeout(() => { try { process.kill(-child.pid, 'SIGKILL'); } catch { /* child may already be gone */ } }, 250);
    }, Math.max(1, Number(check.timeoutSeconds ?? 120)) * 1000);
    child.once('error', (error) => {
      clearTimeout(timeout);
      finish({ status: error.code === 'ENOENT' ? 'missing_executable' : 'failed', error: error.message, exitCode: null, signal: null });
    });
    child.once('close', (code, signal) => {
      clearTimeout(timeout);
      if (timedOut) finish({ status: 'timeout', error: 'check timed out', exitCode: code, signal });
      else if (code === 0) finish({ status: 'passed', exitCode: code, signal: null });
      else finish({ status: 'failed', error: `exit ${code ?? 'null'}${signal ? ` signal ${signal}` : ''}`, exitCode: code, signal });
    });
  });
}

async function commandVerify(root, args) {
  const id = args[0];
  if (!id) throw new HarnessError('usage: verify ID', 2);
  const release = await acquireLock(root);
  let attemptStored;
  try {
    const state = await loadState(root);
    const validation = await validateState(root, state, { includeFreshness: false });
    if (validation.errors.length) throw new HarnessError('state is invalid; verification refused', 1, validation.errors);
    const task = taskById(state.tasks, id);
    if (!task) throw new HarnessError(`unknown live task: ${id}`, 2);
    if (task.state !== 'active') throw new HarnessError(`${id} must be active before verify`, 1);
    const attemptId = `run-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    attemptStored = `${HARNESS}/runs/${attemptId}.json`;
    const logStored = `${HARNESS}/runs/${attemptId}.log`;
    const attempt = {
      schemaVersion: SCHEMA_VERSION,
      id: attemptId,
      taskId: id,
      status: 'running',
      startedAt: new Date().toISOString(),
      checkIds: [...task.verification],
      checks: [],
      fingerprintBefore: null,
      fingerprintAfter: null,
    };
    await atomicWrite(root, attemptStored, attempt);
    await atomicWrite(root, logStored, `attempt ${attemptId} started\n`);
    try {
      attempt.fingerprintBefore = await fingerprint(root, state.config.fingerprintPaths);
    } catch (error) {
      attempt.status = 'failed';
      attempt.failure = { classification: 'input_error', message: error.message };
      task.evidence = { status: 'failed', attemptId, failure: attempt.failure };
      await atomicWrite(root, attemptStored, attempt);
      await atomicWrite(root, STATE_FILES.tasks, state.tasks);
      emit({ ok: false, id, attemptId, status: attempt.status, failure: attempt.failure }, 1);
      return;
    }
    const checks = checkMap(state.config);
    for (const checkId of task.verification) {
      const check = checks.get(checkId);
      if (!check) {
        attempt.checks.push({ id: checkId, status: 'missing_check' });
        continue;
      }
      const result = await runCheck(root, check, logStored);
      attempt.checks.push({ id: checkId, ...result });
      await fs.appendFile(await safePath(root, logStored), `\n[${checkId}] ${commandString(check)}\n${result.stdout}${result.stderr}\nstatus=${result.status}\n`, 'utf8');
      await atomicWrite(root, attemptStored, attempt);
    }
    try {
      attempt.fingerprintAfter = await fingerprint(root, state.config.fingerprintPaths);
    } catch (error) {
      attempt.status = 'failed';
      attempt.failure = { classification: 'input_error_after', message: error.message };
    }
    const requiredFailures = attempt.checks.filter((result) => result.status !== 'passed' && (checks.get(result.id)?.required ?? true));
    const anyFailures = attempt.checks.some((result) => result.status !== 'passed');
    if (!attempt.failure && attempt.fingerprintAfter && attempt.fingerprintBefore.digest !== attempt.fingerprintAfter.digest) {
      attempt.failure = { classification: 'changed_during_verification', message: 'configured inputs changed while checks ran' };
    }
    if (!attempt.failure && requiredFailures.length === 0 && !anyFailures && task.verification.length > 0) {
      attempt.status = 'passed';
      task.state = 'verified';
      task.evidence = {
        status: 'passed',
        attemptId,
        fingerprintBefore: attempt.fingerprintBefore.digest,
        fingerprintAfter: attempt.fingerprintAfter.digest,
        checks: attempt.checks.map(({ id: checkId, status }) => ({ id: checkId, status })),
        verifiedAt: new Date().toISOString(),
      };
    } else {
      attempt.status = 'failed';
      if (!attempt.failure) attempt.failure = { classification: 'check_failed', failedChecks: attempt.checks.filter((result) => result.status !== 'passed').map((result) => result.id) };
      task.evidence = {
        status: 'failed',
        attemptId,
        failure: attempt.failure,
        checks: attempt.checks.map(({ id: checkId, status }) => ({ id: checkId, status })),
      };
    }
    attempt.finishedAt = new Date().toISOString();
    await atomicWrite(root, attemptStored, attempt);
    await atomicWrite(root, STATE_FILES.tasks, state.tasks);
    emit({ ok: attempt.status === 'passed', id, attemptId, status: attempt.status, taskState: task.state, checks: attempt.checks.map(({ id: checkId, status }) => ({ id: checkId, status })), failure: attempt.failure ?? null }, attempt.status === 'passed' ? 0 : 1);
  } finally {
    await release();
  }
}

async function commandHandoff(root) {
  const release = await acquireLock(root);
  try {
    const state = await loadState(root);
    const handoff = state.handoff ?? defaultHandoff();
    const active = state.tasks.tasks.find((task) => task.state === 'active') ?? null;
    const latestAttempt = active?.evidence?.attemptId ?? null;
    const next = {
      ...handoff,
      schemaVersion: SCHEMA_VERSION,
      activeTask: active?.id ?? null,
      git: await gitInfo(root),
      evidence: active?.evidence ?? null,
      latestAttempt,
      updatedAt: new Date().toISOString(),
    };
    await atomicWrite(root, STATE_FILES.handoff, next);
    emit({ ok: true, handoff: next });
  } finally {
    await release();
  }
}

async function commandArchive(root, args) {
  const id = args[0];
  if (!id) throw new HarnessError('usage: archive ID', 2);
  const dryRun = args.includes('--dry-run');
  const release = await acquireLock(root);
  try {
    const state = await loadState(root);
    const validation = await validateState(root, state);
    if (validation.errors.length) throw new HarnessError('state is invalid; archive refused', 1, validation.errors);
    const index = state.tasks.tasks.findIndex((task) => task.id === id);
    if (index === -1) throw new HarnessError(`unknown live task: ${id}`, 2);
    const task = state.tasks.tasks[index];
    if (task.state !== 'passing') throw new HarnessError(`${id} must be passing before archive`, 1);
    const archived = { schemaVersion: SCHEMA_VERSION, archivedAt: new Date().toISOString(), task };
    if (dryRun) { emit({ ok: true, dryRun: true, id, archive: archived }); return; }
    await atomicWrite(root, `${HARNESS}/archive/${id}.json`, archived);
    state.tasks.tasks.splice(index, 1);
    await atomicWrite(root, STATE_FILES.tasks, state.tasks);
    emit({ ok: true, id, archived: true });
  } finally {
    await release();
  }
}

async function main() {
  const { root: requestedRoot, command, rest } = parseCli(process.argv.slice(2));
  const root = await realRoot(requestedRoot);
  if (command === 'init') emit(await init(root));
  else if (command === 'context') await commandContext(root);
  else if (command === 'tasks') await commandTasks(root);
  else if (command === 'validate') await commandValidate(root);
  else if (command === 'verify') await commandVerify(root, rest);
  else if (command === 'handoff') await commandHandoff(root);
  else if (command === 'archive') await commandArchive(root, rest);
  else if (command === 'transition') await commandTransition(root, rest);
  else throw new HarnessError(`unsupported command: ${command}`, 2);
}

main().catch((error) => {
  const code = error instanceof HarnessError ? error.exitCode : 2;
  emit({ ok: false, error: error.message, details: error.details ?? null }, code);
});
