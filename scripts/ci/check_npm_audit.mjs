#!/usr/bin/env node
/** 严格比对 npm audit 生产树 JSON 与已审批、可到期的 Gate A 策略。 */

import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'

const REQUIRED_REVIEW_FIELDS = [
  'actual_usage', 'decision', 'dependency_paths', 'fix_options', 'rationale',
  'reachability', 'regression_scope'
]

function parseArgs(argv) {
  const options = {}
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]
    const value = argv[index + 1]
    if (!key?.startsWith('--') || value === undefined) throw new Error('Invalid arguments')
    options[key.slice(2)] = value
  }
  for (const key of ['report', 'policy', 'lockfile', 'summary']) {
    if (!options[key]) throw new Error(`Missing --${key}`)
  }
  options.today = options.today || new Date().toISOString().slice(0, 10)
  return options
}

function readJson(path, label) {
  try {
    const value = JSON.parse(readFileSync(path, 'utf8'))
    if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error()
    return value
  } catch {
    throw new Error(`Invalid ${label} JSON: ${path}`)
  }
}

function parseIsoDate(value, field) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error(`Policy ${field} must be an ISO date`)
  }
  const timestamp = Date.parse(`${value}T00:00:00Z`)
  if (Number.isNaN(timestamp)) throw new Error(`Policy ${field} must be an ISO date`)
  return timestamp
}

function advisoryId(via) {
  if (typeof via.url !== 'string') throw new Error('npm audit advisory is missing a URL')
  const match = via.url.match(/\/advisories\/(GHSA-[a-z0-9-]+)$/i)
  if (!match) throw new Error(`Unsupported npm advisory URL: ${via.url}`)
  return match[1]
}

function resolvedAdvisories(name, vulnerabilities, seen = new Set()) {
  if (seen.has(name)) throw new Error(`Cyclic npm vulnerability graph at ${name}`)
  const item = vulnerabilities[name]
  if (!item || !Array.isArray(item.via)) throw new Error(`Invalid npm vulnerability entry: ${name}`)
  const nextSeen = new Set(seen).add(name)
  const advisories = new Set()
  for (const via of item.via) {
    if (typeof via === 'string') {
      for (const identifier of resolvedAdvisories(via, vulnerabilities, nextSeen)) advisories.add(identifier)
    } else if (via && typeof via === 'object') {
      advisories.add(advisoryId(via))
    } else {
      throw new Error(`Invalid npm vulnerability path: ${name}`)
    }
  }
  return [...advisories].sort()
}

function validateReport(report) {
  if (report.auditReportVersion !== 2 || !report.vulnerabilities || !report.metadata?.vulnerabilities) {
    throw new Error('Invalid npm audit report: auditReportVersion 2 and vulnerability metadata are required')
  }
  return report.vulnerabilities
}

function validatePolicy(policy, today) {
  if (policy.schema_version !== 1) throw new Error('Unsupported npm audit policy schema_version')
  if (policy.tool !== 'npm audit 11.6.2' || policy.audited_scope !== 'production dependencies (--omit=dev)') {
    throw new Error('npm audit policy tool/scope is invalid')
  }
  for (const field of ['owner', 'risk_accepted_by']) {
    if (typeof policy[field] !== 'string' || !policy[field].trim()) throw new Error(`npm audit policy ${field} is required`)
  }
  const reviewed = parseIsoDate(policy.reviewed_on, 'reviewed_on')
  const expires = parseIsoDate(policy.expires_on, 'expires_on')
  const current = parseIsoDate(today, 'today')
  if (reviewed > current) throw new Error('npm audit policy review date is in the future')
  if (expires < current) throw new Error('npm audit policy has expired')
  if ((expires - reviewed) / 86400000 > 92) throw new Error('npm audit policy exception exceeds 92 days')
  if (!Array.isArray(policy.expected_vulnerabilities)) throw new Error('npm audit policy expected_vulnerabilities is required')
}

function validateReview(entry) {
  for (const field of REQUIRED_REVIEW_FIELDS) {
    if (!(field in entry)) throw new Error(`npm audit policy review field is missing: ${field}`)
  }
  if (entry.decision !== 'time-boxed-exception' || entry.reachability === 'unknown') {
    throw new Error(`npm audit exception must be time-boxed with known reachability: ${entry.package}`)
  }
  if (!Array.isArray(entry.dependency_paths) || entry.dependency_paths.length === 0) {
    throw new Error(`npm audit dependency_paths is required: ${entry.package}`)
  }
  for (const field of ['actual_usage', 'fix_options', 'rationale', 'regression_scope']) {
    if (typeof entry[field] !== 'string' || !entry[field].trim()) throw new Error(`npm audit ${field} is required: ${entry.package}`)
  }
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  const errors = []
  let report = {}
  let policy = {}
  let vulnerabilities = {}
  try {
    report = readJson(options.report, 'npm audit report')
    policy = readJson(options.policy, 'npm audit policy')
    const lockfile = readJson(options.lockfile, 'npm lockfile')
    vulnerabilities = validateReport(report)
    validatePolicy(policy, options.today)

    const expected = new Map(policy.expected_vulnerabilities.map((entry) => [entry.package, entry]))
    if (expected.size !== policy.expected_vulnerabilities.length) {
      throw new Error('npm audit policy contains duplicate package entries')
    }
    const actualNames = new Set(Object.keys(vulnerabilities))
    for (const name of [...actualNames].filter((item) => !expected.has(item)).sort()) {
      errors.push(`Unexpected vulnerable package: ${name}`)
    }
    for (const name of [...expected.keys()].filter((item) => !actualNames.has(item)).sort()) {
      errors.push(`Policy package is no longer vulnerable: ${name}`)
    }

    for (const [name, entry] of expected) {
      validateReview(entry)
      const actual = vulnerabilities[name]
      if (!actual) continue
      const installed = lockfile.packages?.[`node_modules/${name}`]?.version
      if (installed !== entry.installed_version) errors.push(`Installed version changed: ${name} expected=${entry.installed_version} actual=${installed}`)
      if (actual.severity !== entry.severity) errors.push(`Severity changed: ${name}`)
      if (actual.isDirect !== entry.is_direct) errors.push(`Direct dependency classification changed: ${name}`)
      if (actual.range !== entry.affected_range) errors.push(`Affected range changed: ${name}`)
      const advisories = resolvedAdvisories(name, vulnerabilities)
      if (JSON.stringify(advisories) !== JSON.stringify([...entry.advisories].sort())) {
        errors.push(`Advisory set changed: ${name}`)
      }
    }

    const expectedCounts = policy.expected_severity_counts
    const actualCounts = report.metadata.vulnerabilities
    for (const severity of ['info', 'low', 'moderate', 'high', 'critical', 'total']) {
      if (actualCounts[severity] !== expectedCounts[severity]) errors.push(`Severity count changed: ${severity}`)
    }
    const globalAdvisories = [...new Set(Object.keys(vulnerabilities).flatMap((name) => resolvedAdvisories(name, vulnerabilities)))].sort()
    if (JSON.stringify(globalAdvisories) !== JSON.stringify([...policy.expected_advisories].sort())) {
      errors.push('Global npm advisory set changed')
    }
  } catch (error) {
    errors.push(error.message)
  }

  const counts = report.metadata?.vulnerabilities || {}
  const summary = {
    schema_version: 1,
    passed: errors.length === 0,
    audit_tool: 'npm audit 11.6.2',
    audited_scope: 'production dependencies (--omit=dev)',
    vulnerable_package_count: Object.keys(vulnerabilities).length,
    severity_counts: {
      critical: counts.critical || 0,
      high: counts.high || 0,
      moderate: counts.moderate || 0
    },
    advisory_count: policy.expected_advisories?.length || 0,
    policy_expires_on: policy.expires_on,
    errors
  }
  mkdirSync(dirname(options.summary), { recursive: true })
  writeFileSync(options.summary, `${JSON.stringify(summary, null, 2)}\n`)
  if (errors.length) {
    for (const error of errors) process.stderr.write(`${error}\n`)
    return 1
  }
  process.stdout.write(`npm dependency audit policy passed: vulnerable_packages=${Object.keys(vulnerabilities).length}\n`)
  return 0
}

try {
  process.exitCode = main()
} catch (error) {
  process.stderr.write(`${error.message}\n`)
  process.exitCode = 1
}
