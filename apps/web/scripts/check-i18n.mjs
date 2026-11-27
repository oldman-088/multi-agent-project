#!/usr/bin/env node
/**
 * i18n completeness gate.
 *
 * Fails (exit code 1) when any shipped locale (ar, fa) is not a complete,
 * consistent translation of the reference locale (en):
 *   - a key is missing, empty or not a string,
 *   - a locale has keys the reference does not have,
 *   - `{{placeholder}}` names differ from the reference.
 *
 * Usage:
 *   node scripts/check-i18n.mjs                  # check the shipped catalogues
 *   node scripts/check-i18n.mjs --json           # machine-readable report
 *   node scripts/check-i18n.mjs --allow <lang>   # report a locale without failing (draft locales)
 *
 * The rules live in `src/i18n/coverage.ts` and are covered by
 * `src/i18n/coverage.test.ts`, so the CLI and the tests can never disagree.
 *
 * Node ≥ 22.18 runs this `.mjs` file and its TypeScript imports directly
 * (type stripping), so the check needs no build step and no extra dependency.
 */

import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { checkAllCatalogues, describeIssue, referenceKeys } from '../src/i18n/coverage.ts';
import { SUPPORTED_LANGUAGES } from '../src/i18n/languages.ts';
import { TRANSLATIONS } from '../src/i18n/resources.ts';

const REFERENCE_LANGUAGE = 'en';

/** Parse `--flag`, `--flag value` and `--flag=value`. */
function parseArgs(argv) {
  const flags = { json: false, allow: [], help: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--json') flags.json = true;
    else if (argument === '--help' || argument === '-h') flags.help = true;
    else if (argument === '--allow') {
      const next = argv[index + 1];
      if (!next) throw new Error('--allow needs a language tag, for example: --allow fa');
      flags.allow.push(next);
      index += 1;
    } else if (argument.startsWith('--allow=')) {
      flags.allow.push(argument.slice('--allow='.length));
    } else {
      throw new Error(`Unknown argument: ${argument} (see --help)`);
    }
  }
  return flags;
}

const USAGE = `i18n completeness check

  node scripts/check-i18n.mjs [--json] [--allow <lang>]...

Reference locale: ${REFERENCE_LANGUAGE}
Shipped locales:  ${SUPPORTED_LANGUAGES.join(', ')}

Exit code 0 when every locale is complete, 1 otherwise.
`;

function main() {
  /** @type {{json: boolean, allow: string[], help: boolean}} */
  let flags;
  try {
    flags = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(`check-i18n: ${error instanceof Error ? error.message : String(error)}`);
    console.error(USAGE);
    return 2;
  }

  if (flags.help) {
    console.log(USAGE);
    return 0;
  }

  for (const language of flags.allow) {
    if (!SUPPORTED_LANGUAGES.includes(language)) {
      console.error(`check-i18n: --allow expects one of ${SUPPORTED_LANGUAGES.join(', ')}, got "${language}"`);
      return 2;
    }
    if (language === REFERENCE_LANGUAGE) {
      console.error(`check-i18n: --allow cannot target the reference locale "${REFERENCE_LANGUAGE}"`);
      return 2;
    }
  }

  const reference = TRANSLATIONS[REFERENCE_LANGUAGE];
  const gross = checkAllCatalogues(TRANSLATIONS, REFERENCE_LANGUAGE);
  const issues = gross.filter((issue) => !flags.allow.includes(issue.language));

  const report = {
    referenceLanguage: REFERENCE_LANGUAGE,
    referenceKeyCount: referenceKeys(reference).length,
    languages: Object.fromEntries(
      SUPPORTED_LANGUAGES.map((language) => {
        const isReference = language === REFERENCE_LANGUAGE;
        const languageIssues = gross.filter((issue) => issue.language === language);
        const entries = Object.keys(TRANSLATIONS[language]).length;
        return [
          language,
          {
            reference: isReference,
            allowed: flags.allow.includes(language),
            entries,
            issues: languageIssues.length,
            coveragePercent: isReference
              ? 100
              : Math.round((100 * (referenceKeys(reference).length - languageIssues.filter((i) => i.kind === 'missing-key').length)) / referenceKeys(reference).length * 10) / 10,
          },
        ];
      }),
    ),
    totalIssues: issues.length,
    issueDetails: issues.map((issue) => ({ language: issue.language, key: issue.key, kind: issue.kind, detail: issue.detail })),
  };

  if (flags.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    for (const language of SUPPORTED_LANGUAGES) {
      const languageIssues = gross.filter((issue) => issue.language === language);
      const marker = language === REFERENCE_LANGUAGE ? '(reference)' : languageIssues.length === 0 ? 'OK' : `${languageIssues.length} issue(s)`;
      console.log(`${language.padEnd(3)} ${String(Object.keys(TRANSLATIONS[language]).length).padStart(4)} keys  ${marker}`);
      for (const issue of languageIssues) {
        const allowed = flags.allow.includes(language) ? ' (allowed)' : '';
        console.log(`    - ${describeIssue(issue)}${allowed}`);
      }
    }
    console.log('');
  }

  if (issues.length > 0) {
    console.error(`check-i18n: FAILED — ${issues.length} problem(s) across ${new Set(issues.map((i) => i.language)).size} locale(s).`);
    for (const issue of issues) console.error(`  ${describeIssue(issue)}`);
    return 1;
  }

  console.log(`check-i18n: OK — ${referenceKeys(reference).length} keys complete in ${SUPPORTED_LANGUAGES.join(', ')}.`);
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  process.exitCode = main();
}
