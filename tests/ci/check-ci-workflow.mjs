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
 *     Playwright against them.
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

section('Job guards (valid GitHub Actions expressions)', () => {
  // A bare shell file test (`if: -f <file>`) is NOT a valid GitHub Actions
  // expression: it makes the whole workflow fail to parse ("workflow file
  // issue") and no jobs are created. Guards must use hashFiles(...).
  check(
    'does not use the invalid `if: -f <file>` shell test',
    !/^\s*if:\s*-f\s/m.test(content)
  );
  check('guards presence with hashFiles expressions', (content.match(/hashFiles\(/g) || []).length >= 3);
  check(
    'guards every conditional job (typecheck, check, e2e)',
    /typecheck:[\s\S]*?if:\s*\$\{\{\s*hashFiles\(/.test(content) &&
      /check:[\s\S]*?if:\s*\$\{\{\s*hashFiles\(/.test(content) &&
      /e2e:[\s\S]*?if:\s*\$\{\{\s*hashFiles\(/.test(content)
  );
});

console.log(`\n${passed} passed, ${failures.length} failed.`);
if (failures.length > 0) {
  console.error('Failed checks:');
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log('CI workflow validation passed.');
