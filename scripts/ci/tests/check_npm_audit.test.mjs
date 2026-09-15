import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import test, { afterEach } from 'node:test'

const REPOSITORY_ROOT = resolve(import.meta.dirname, '..', '..', '..')
const CHECKER = join(REPOSITORY_ROOT, 'scripts', 'ci', 'check_npm_audit.mjs')
const POLICY = join(REPOSITORY_ROOT, 'security', 'dependency_audit', 'npm-policy.json')
const LOCKFILE = join(REPOSITORY_ROOT, 'miniapp', 'package-lock.json')
const createdRoots = new Set()

afterEach(() => {
  for (const root of createdRoots) rmSync(root, { recursive: true, force: true })
  createdRoots.clear()
})

function fixtureReport() {
  return JSON.parse(readFileSync(join(REPOSITORY_ROOT, 'security', 'dependency_audit', 'npm-audit-fixture.json'), 'utf8'))
}

function runChecker(report, policy = POLICY, today = '2026-08-31') {
  const root = mkdtempSync(join(tmpdir(), 'pinkdoohub-npm-audit-'))
  createdRoots.add(root)
  const reportPath = join(root, 'report.json')
  const summaryPath = join(root, 'summary.json')
  writeFileSync(reportPath, JSON.stringify(report))
  const result = spawnSync(process.execPath, [
    CHECKER,
    '--report', reportPath,
    '--policy', policy,
    '--lockfile', LOCKFILE,
    '--summary', summaryPath,
    '--today', today
  ], { cwd: REPOSITORY_ROOT, encoding: 'utf8' })
  return { result, summaryPath, root }
}

test('accepts only the exact reviewed production dependency findings', () => {
  const { result, summaryPath } = runChecker(fixtureReport())

  assert.equal(result.status, 0, result.stderr)
  const summary = JSON.parse(readFileSync(summaryPath, 'utf8'))
  assert.equal(summary.passed, true)
  assert.equal(summary.vulnerable_package_count, 10)
  assert.deepEqual(summary.severity_counts, { critical: 5, high: 1, moderate: 4 })
  assert.equal(summary.advisory_count, 5)
})

test('rejects a newly reported vulnerable package', () => {
  const report = fixtureReport()
  report.vulnerabilities['new-package'] = {
    name: 'new-package', severity: 'high', isDirect: false,
    via: [{ source: 999, name: 'new-package', severity: 'high', url: 'https://github.com/advisories/GHSA-xxxx-yyyy-zzzz' }],
    effects: [], range: '<2.0.0', nodes: ['node_modules/new-package'], fixAvailable: false
  }
  report.metadata.vulnerabilities.high += 1
  report.metadata.vulnerabilities.total += 1

  const { result } = runChecker(report)

  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /unexpected vulnerable package/i)
})

test('rejects an expired policy', () => {
  const policy = JSON.parse(readFileSync(POLICY, 'utf8'))
  policy.expires_on = '2026-08-30'
  const root = mkdtempSync(join(tmpdir(), 'pinkdoohub-npm-policy-'))
  createdRoots.add(root)
  const policyPath = join(root, 'policy.json')
  writeFileSync(policyPath, JSON.stringify(policy))

  const { result } = runChecker(fixtureReport(), policyPath)

  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /expired/i)
})

test('rejects malformed registry error JSON instead of treating it as a clean audit', () => {
  const { result } = runChecker({ error: { code: 'EAUDITENDPOINT' } })

  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /audit report/i)
})
