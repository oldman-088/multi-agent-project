#!/usr/bin/env node
/**
 * Automated test for the CI workflow configuration.
 *
 * Validates `.github/workflows/ci.yml` so the E2E pull request's CI contract is
 * enforced by a real, runnable check rather than by eyeballing the YAML. It runs
 * in the `validate` job of the same workflow (and locally with `node`), using
 * only Node built-ins — no extra dependencies.
 *
 * Checks enforced:
 *   - the workflow file exists and declares name `ci`;
 *   - it is triggered on push and pull_request (so PR heads get a check);
 *   - it sets up both runtimes (Node and Python) and installs dependencies;
 *   - it runs the project check script (scripts/check.sh);
 *   - it has a TypeScript type-check job;
 *   - it has an E2E job that starts a local frontend + backend and runs
 *     Playwright against them;
 *   - every slice-presence guard is a valid GitHub Actions expression placed on
 *     the step that needs the slice (never on a job-level `if`).
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const workflowPath = join(here, '..', '..', '.github', 'workflows', 'ci.yml');

let passed = 0;
const failures = [];

function check(label, condition, detail = '') {
  if (condition) {
    passed += 1;
    console.log(`  ✅ ${label}`);
  } else {
    failures.push(label);
    console.log(`  ❌ ${label}${detail ? ` — ${detail}` : ''}`);
  }
}

function has(content, needle) {
  return content.includes(needle);
}

function section(name, body) {
  console.log(`\n${name}`);
  body();
}

let content;
try {
  content = readFileSync(workflowPath, 'utf8');
} catch (err) {
  console.error(`Cannot read ${workflowPath}: ${err.message}`);
  process.exit(1);
}

section('Workflow file', () => {
  check('ci.yml is non-empty', content.trim().length > 0);
  check('declares name: ci', /^name:\s*ci\s*$/m.test(content));
});

section('Triggers', () => {
  check('triggers on push', /^on:\s*$/m.test(content) && has(content, 'push:'));
  check('triggers on pull_request', has(content, 'pull_request:'));
  check('allows manual dispatch', has(content, 'workflow_dispatch:'));
});

section('Environment + dependencies', () => {
  check('sets up Node', has(content, 'actions/setup-node@v4'));
  check('sets up Python', has(content, 'actions/setup-python@v5'));
  check('installs Node dependencies (npm ci)', has(content, 'npm ci'));
  check('installs backend dependencies (pip install)', has(content, 'pip install'));
});

section('Check script', () => {
  check('runs the project check script (scripts/check.sh)', has(content, 'scripts/check.sh'));
});

section('TypeScript gate', () => {
  check('has a typecheck job', /^  typecheck:\s*$/m.test(content));
  check('runs a TypeScript type check (tsc --noEmit)', has(content, 'tsc --noEmit'));
});

section('E2E gate', () => {
  check('has an e2e job', /^  e2e:\s*$/m.test(content));
  check('installs Playwright browsers', has(content, 'playwright install'));
  check('starts the backend locally (uvicorn)', has(content, 'uvicorn backend.app.main:app'));
  check(
    'starts a local frontend dev server',
    has(content, 'start:frontend') || has(content, 'npm run "$frontend_script"')
  );
  check('waits for a health endpoint', has(content, 'wait_http'));
  check('runs the Playwright suite', has(content, 'npx playwright test'));
  check(
    'runs E2E against a configurable base URL',
    has(content, 'PLAYWRIGHT_BASE_URL') && has(content, 'API_BASE_URL')
  );
});

section('Safety', () => {
  // The workflow must never carry a real credential. CI-only throwaway values
  // for the two secrets the backend needs are allowed; flag obvious real keys.
  check(
    'does not hard-code a GitHub token',
    !/gh[pousr]_[A-Za-z0-9]{20,}/.test(content) && !/github_token:\s*[A-Za-z0-9]/.test(content)
  );
  check('does not commit a .env file', !/^\s*\.env\s*$/m.test(content));
});

section('Presence guards (step-level only)', () => {
  // Two constructs make GitHub reject the ENTIRE workflow file at parse time
  // ("workflow file issue", zero jobs created):
  //   1. a bare shell file test in `if:` (`if: -f <file>`) — not a valid
  //      GitHub Actions expression at all;
  //   2. `hashFiles(...)` in a JOB-level `if:` — `hashFiles()` is only
  //      available in STEP-level conditions, so it must never appear on a
  //      job `if:`. It IS valid on a step `if:`, after checkout.
  // Both are caught here so the workflow can never silently produce a red
  // run with no jobs.
  check(
    'does not use the invalid `if: -f <file>` shell test',
    !/^\s*if:\s*-f\s/m.test(content)
  );
  // Job-level keys are indented 4 spaces in this file; step keys 8 spaces.
  check(
    'does not use hashFiles in a job-level if (invalid, rejects the whole file)',
    !/^ {4}if:.*hashFiles\(/m.test(content)
  );
  check(
    'keeps hashFiles guards at the step level',
    (/^ {8}if:.*hashFiles\(/m.test(content) &&
      (content.match(/^ {8}if:.*hashFiles\(/gm) || []).length >= 3)
  );
  check(
    'gates the TypeScript job on tsconfig.json at step level',
    /^ {8}if:.*hashFiles\('tsconfig\.json'\)/m.test(content)
  );
  check(
    'gates the check-script job on scripts/check.sh at step level',
    /^ {8}if:.*hashFiles\('scripts\/check\.sh'\)/m.test(content)
  );
  check(
    'gates the E2E job on a detect step output (no job-level if)',
    has(content, 'steps.detect.outputs.frontend_present')
  );
});

console.log(`\n${passed} passed, ${failures.length} failed.`);
if (failures.length > 0) {
  console.error('Failed checks:');
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log('CI workflow validation passed.');
