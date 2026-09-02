#!/usr/bin/env node

import { createHash } from 'node:crypto'
import {
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  writeFileSync
} from 'node:fs'
import { basename, dirname, isAbsolute, relative, resolve, sep } from 'node:path'
import { isDeepStrictEqual } from 'node:util'

const MAIN_PACKAGE_LIMIT = 2 * 1024 * 1024
const SUBPACKAGE_LIMIT = 2 * 1024 * 1024
const SUBPACKAGES_TOTAL_LIMIT = 30 * 1024 * 1024
const ARTIFACT_TOTAL_LIMIT = MAIN_PACKAGE_LIMIT + SUBPACKAGES_TOTAL_LIMIT
const TEXT_EXTENSIONS = new Set([
  '.css', '.html', '.js', '.json', '.txt', '.wxml', '.wxs', '.wxss'
])
const H5_ONLY_MARKERS = [
  '@tarojs/components/dist-h5',
  '@tarojs/plugin-platform-h5',
  'tarojs_plugin-platform-h5'
]
const SECRET_MARKERS = [
  { name: 'private key', pattern: /-----BEGIN (?:EC |OPENSSH |RSA )?PRIVATE KEY-----/ },
  { name: 'GitHub token', pattern: /gh[pousr]_[A-Za-z0-9]{36,255}/ },
  { name: 'AWS access key', pattern: /AKIA[0-9A-Z]{16}/ },
  { name: 'OpenAI key', pattern: /sk-[A-Za-z0-9_-]{32,}/ }
]

function parseArguments(argv) {
  const values = new Map()
  for (let index = 0; index < argv.length; index += 2) {
    const option = argv[index]
    const value = argv[index + 1]
    if (!option?.startsWith('--') || !value) {
      throw new Error('usage: --artifact-root <dir> --manifest <file>')
    }
    values.set(option, value)
  }
  const artifactRoot = values.get('--artifact-root')
  const projectConfig = values.get('--project-config')
  const manifest = values.get('--manifest')
  if (!artifactRoot || !projectConfig || !manifest || values.size !== 3) {
    throw new Error(
      'usage: --artifact-root <dir> --project-config <file> --manifest <file>'
    )
  }
  return {
    artifactRoot: resolve(artifactRoot),
    projectConfig: resolve(projectConfig),
    manifest: resolve(manifest)
  }
}

function validateExpectedOrigin(rawOrigin) {
  if (!rawOrigin) {
    throw new Error('WEAPP_EXPECTED_ORIGIN is required')
  }
  let origin
  try {
    origin = new URL(rawOrigin)
  } catch {
    throw new Error('WEAPP_EXPECTED_ORIGIN must be a valid HTTPS Origin')
  }
  if (
    origin.protocol !== 'https:' ||
    origin.origin !== rawOrigin ||
    origin.username ||
    origin.password ||
    origin.pathname !== '/' ||
    origin.search ||
    origin.hash
  ) {
    throw new Error('WEAPP_EXPECTED_ORIGIN must be an HTTPS Origin without path or credentials')
  }
  return origin
}

function parseReleaseEligibility(value) {
  if (value !== '0' && value !== '1') {
    throw new Error('WEAPP_RELEASE_ELIGIBLE must be exactly 0 or 1')
  }
  return value === '1'
}

function isInside(parent, child) {
  const pathFromParent = relative(parent, child)
  return pathFromParent !== '' && !pathFromParent.startsWith(`..${sep}`) && pathFromParent !== '..'
}

function listArtifactFiles(root) {
  if (!lstatSync(root).isDirectory()) {
    throw new Error('artifact root must be a directory')
  }
  const files = []

  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const absolutePath = resolve(directory, entry.name)
      const artifactPath = relative(root, absolutePath).split(sep).join('/')
      if (entry.isSymbolicLink()) {
        throw new Error(`artifact must not contain symbolic links: ${artifactPath}`)
      }
      if (entry.isDirectory()) {
        visit(absolutePath)
      } else if (entry.isFile()) {
        files.push({ absolutePath, artifactPath })
      } else {
        throw new Error(`artifact contains an unsupported filesystem entry: ${artifactPath}`)
      }
    }
  }

  visit(root)
  return files.sort((left, right) => left.artifactPath.localeCompare(right.artifactPath))
}

function extension(path) {
  const dotIndex = path.lastIndexOf('.')
  return dotIndex === -1 ? '' : path.slice(dotIndex).toLowerCase()
}

function readTextFile(path) {
  const content = readFileSync(path)
  if (content.includes(0) || !TEXT_EXTENSIONS.has(extension(path))) {
    return null
  }
  return content.toString('utf8')
}

function readJson(root, artifactPath) {
  const absolutePath = resolve(root, artifactPath)
  try {
    return JSON.parse(readFileSync(absolutePath, 'utf8'))
  } catch {
    throw new Error(`required artifact JSON is missing or invalid: ${artifactPath}`)
  }
}

function readProjectConfig(path) {
  try {
    const entry = lstatSync(path)
    if (!entry.isFile() || entry.isSymbolicLink()) {
      throw new Error('not a regular file')
    }
    const content = readFileSync(path)
    return {
      content,
      document: JSON.parse(content.toString('utf8'))
    }
  } catch {
    throw new Error('required project config JSON is missing or invalid')
  }
}

function packageRoots(appConfig) {
  const configured = appConfig.subPackages ?? appConfig.subpackages
  if (!Array.isArray(configured)) {
    throw new Error('app.json must declare the admin subpackage')
  }
  const roots = configured.map((item) => String(item?.root ?? '').replace(/^\/+|\/+$/g, ''))
  if (!roots.includes('admin')) {
    throw new Error('app.json must declare the admin subpackage')
  }
  if (roots.some((root) => !root || root.includes('..') || root.includes('\\'))) {
    throw new Error('app.json contains an invalid subpackage root')
  }
  if (new Set(roots).size !== roots.length) {
    throw new Error('app.json contains duplicate subpackage roots')
  }
  return roots.sort()
}

function validateTextContent(artifactPath, text, expectedOrigin) {
  if (text.includes('sourceMappingURL=')) {
    throw new Error(`source map reference found: ${artifactPath}`)
  }
  for (const marker of H5_ONLY_MARKERS) {
    if (text.includes(marker)) {
      throw new Error(`H5-only marker found in WeChat artifact: ${artifactPath}`)
    }
  }
  for (const marker of SECRET_MARKERS) {
    if (marker.pattern.test(text)) {
      throw new Error(`Secret marker (${marker.name}) found: ${artifactPath}`)
    }
  }

  const origins = text.match(/https?:\/\/(?:\[[0-9a-f:]+\]|[a-z0-9.-]+)(?::\d{1,5})?/gi) ?? []
  for (const rawOrigin of origins) {
    const parsed = new URL(rawOrigin)
    const host = parsed.hostname.replace(/^\[|\]$/g, '').toLowerCase()
    if (
      host === 'localhost' ||
      host.endsWith('.localhost') ||
      host === '127.0.0.1' ||
      host === '0.0.0.0' ||
      host === '::1'
    ) {
      throw new Error(`local HTTP Origin found: ${artifactPath}`)
    }
    if (host.endsWith('.example.invalid')) {
      throw new Error(`placeholder Origin found: ${artifactPath}`)
    }
  }

  return text.includes(expectedOrigin)
}

function calculateSizes(files, roots) {
  const subpackages = Object.fromEntries(roots.map((root) => [root, 0]))
  let main = 0
  let total = 0

  for (const file of files) {
    total += file.size
    const matchingRoot = roots.find((root) => file.path.startsWith(`${root}/`))
    if (matchingRoot) {
      subpackages[matchingRoot] += file.size
    } else {
      main += file.size
    }
  }

  const subpackagesTotal = Object.values(subpackages).reduce((sum, size) => sum + size, 0)
  if (main > MAIN_PACKAGE_LIMIT) {
    throw new Error(`main package exceeds ${MAIN_PACKAGE_LIMIT} raw bytes`)
  }
  for (const [root, size] of Object.entries(subpackages)) {
    if (size > SUBPACKAGE_LIMIT) {
      throw new Error(`subpackage ${root} exceeds ${SUBPACKAGE_LIMIT} raw bytes`)
    }
  }
  if (subpackagesTotal > SUBPACKAGES_TOTAL_LIMIT || total > ARTIFACT_TOTAL_LIMIT) {
    throw new Error('combined WeChat artifact exceeds the frozen raw-size limits')
  }
  return { main, subpackages, subpackages_total: subpackagesTotal, total }
}

function checksumPathFor(manifestPath) {
  return manifestPath.endsWith('.json')
    ? `${manifestPath.slice(0, -'.json'.length)}.sha256`
    : `${manifestPath}.sha256`
}

function run() {
  const {
    artifactRoot,
    projectConfig,
    manifest
  } = parseArguments(process.argv.slice(2))
  if (
    !isAbsolute(artifactRoot) ||
    !isAbsolute(projectConfig) ||
    !isAbsolute(manifest)
  ) {
    throw new Error('artifact, project config and manifest paths must resolve absolutely')
  }
  if (isInside(artifactRoot, manifest) || artifactRoot === manifest) {
    throw new Error('manifest must be written outside the artifact root')
  }
  if (isInside(artifactRoot, projectConfig) || artifactRoot === projectConfig) {
    throw new Error('project config must be supplied from outside the compiled artifact root')
  }

  const expectedOrigin = validateExpectedOrigin(process.env.WEAPP_EXPECTED_ORIGIN)
  const releaseEligible = parseReleaseEligibility(process.env.WEAPP_RELEASE_ELIGIBLE)
  if (releaseEligible && expectedOrigin.hostname.endsWith('.test')) {
    throw new Error('reserved CI Origin cannot produce a release-eligible artifact')
  }

  const projectConfigFile = readProjectConfig(projectConfig)
  if (projectConfigFile.document?.miniprogramRoot !== 'dist/weapp/') {
    throw new Error('project.config.json must target dist/weapp/')
  }
  if (projectConfigFile.document?.setting?.uploadWithSourceMap !== false) {
    throw new Error('project.config.json must disable source map upload')
  }
  const roots = packageRoots(readJson(artifactRoot, 'app.json'))
  const artifactFiles = listArtifactFiles(artifactRoot)
  if (artifactFiles.length === 0) {
    throw new Error('artifact contains no files')
  }
  const copiedProjectConfig = artifactFiles.find(
    (file) => file.artifactPath === 'project.config.json'
  )
  if (copiedProjectConfig) {
    const copiedDocument = readJson(
      artifactRoot,
      copiedProjectConfig.artifactPath
    )
    const expectedCopiedDocument = {
      ...projectConfigFile.document,
      miniprogramRoot: './'
    }
    if (!isDeepStrictEqual(copiedDocument, expectedCopiedDocument)) {
      throw new Error(
        'compiled project.config.json must match the normalized project-root config'
      )
    }
  }

  let expectedOriginFound = false
  const files = artifactFiles.map(({ absolutePath, artifactPath }) => {
    if (artifactPath.toLowerCase().endsWith('.map')) {
      throw new Error(`source map file found: ${artifactPath}`)
    }
    const text = readTextFile(absolutePath)
    if (text !== null) {
      expectedOriginFound = validateTextContent(
        artifactPath,
        text,
        expectedOrigin.origin
      ) || expectedOriginFound
    }
    const content = readFileSync(absolutePath)
    return {
      path: artifactPath,
      size: content.length,
      sha256: createHash('sha256').update(content).digest('hex')
    }
  })
  if (!expectedOriginFound) {
    throw new Error('expected API Origin was not found in the WeChat artifact')
  }

  const sizes = calculateSizes(files, roots)
  const manifestDocument = {
    schema_version: 1,
    artifact_kind: releaseEligible ? 'wechat-release-candidate' : 'wechat-ci-non-release',
    release_eligible: releaseEligible,
    expected_origin: expectedOrigin.origin,
    git_sha: process.env.GITHUB_SHA || 'local-uncommitted',
    workflow_run_id: process.env.GITHUB_RUN_ID || 'local',
    project_config: {
      path: basename(projectConfig),
      size: projectConfigFile.content.length,
      sha256: createHash('sha256').update(projectConfigFile.content).digest('hex')
    },
    limits: {
      main_package_bytes: MAIN_PACKAGE_LIMIT,
      subpackage_bytes: SUBPACKAGE_LIMIT,
      subpackages_total_bytes: SUBPACKAGES_TOTAL_LIMIT,
      artifact_total_bytes: ARTIFACT_TOTAL_LIMIT
    },
    sizes,
    file_count: files.length,
    files
  }
  const manifestBytes = Buffer.from(`${JSON.stringify(manifestDocument, null, 2)}\n`)
  mkdirSync(dirname(manifest), { recursive: true })
  writeFileSync(manifest, manifestBytes)
  const manifestChecksum = createHash('sha256').update(manifestBytes).digest('hex')
  const checksumPath = checksumPathFor(manifest)
  writeFileSync(checksumPath, `${manifestChecksum}  ${basename(manifest)}\n`)

  console.log(
    `WeChat artifact verified: files=${files.length} main=${sizes.main} ` +
    `subpackages=${sizes.subpackages_total} total=${sizes.total} ` +
    `release_eligible=${releaseEligible}`
  )
  console.log(`Manifest SHA-256: ${manifestChecksum}`)
}

try {
  run()
} catch (error) {
  console.error(`WeChat artifact check failed: ${error.message}`)
  process.exitCode = 1
}
