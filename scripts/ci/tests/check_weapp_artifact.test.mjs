import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import test, { afterEach } from 'node:test'

const REPOSITORY_ROOT = resolve(import.meta.dirname, '..', '..', '..')
const CHECKER = join(REPOSITORY_ROOT, 'scripts', 'ci', 'check_weapp_artifact.mjs')
const EXPECTED_ORIGIN = 'https://api.ci.pinkdoohub.test'
const createdRoots = new Set()

afterEach(() => {
  for (const root of createdRoots) {
    rmSync(root, { recursive: true, force: true })
  }
  createdRoots.clear()
})

function createFixture(mainSource = `const apiOrigin = '${EXPECTED_ORIGIN}'`) {
  const root = mkdtempSync(join(tmpdir(), 'pinkdoohub-weapp-check-'))
  createdRoots.add(root)
  const artifactRoot = join(root, 'weapp')
  mkdirSync(join(artifactRoot, 'admin'), { recursive: true })
  writeFileSync(join(artifactRoot, 'app.json'), JSON.stringify({
    pages: ['pages/index/index'],
    subPackages: [{ root: 'admin', pages: ['pages/users/index'] }]
  }))
  writeFileSync(join(artifactRoot, 'project.config.json'), JSON.stringify({
    miniprogramRoot: './',
    setting: { uploadWithSourceMap: false }
  }))
  writeFileSync(join(artifactRoot, 'app.js'), mainSource)
  writeFileSync(join(artifactRoot, 'admin', 'page.js'), 'module.exports = {}')
  return {
    root,
    artifactRoot,
    manifest: join(root, 'weapp-manifest.json')
  }
}

function runChecker(fixture, extraEnvironment = {}) {
  return spawnSync(process.execPath, [
    CHECKER,
    '--artifact-root', fixture.artifactRoot,
    '--manifest', fixture.manifest
  ], {
    encoding: 'utf8',
    env: {
      ...process.env,
      WEAPP_EXPECTED_ORIGIN: EXPECTED_ORIGIN,
      WEAPP_RELEASE_ELIGIBLE: '0',
      GITHUB_SHA: '0123456789abcdef',
      GITHUB_RUN_ID: '12345',
      ...extraEnvironment
    }
  })
}

test('writes a traceable manifest and aggregate checksum for a valid CI artifact', () => {
  const fixture = createFixture()

  const result = runChecker(fixture)

  assert.equal(result.status, 0, result.stderr)
  const manifestBytes = readFileSync(fixture.manifest)
  const manifest = JSON.parse(manifestBytes.toString('utf8'))
  assert.equal(manifest.artifact_kind, 'wechat-ci-non-release')
  assert.equal(manifest.release_eligible, false)
  assert.equal(manifest.expected_origin, EXPECTED_ORIGIN)
  assert.equal(manifest.git_sha, '0123456789abcdef')
  assert.equal(manifest.workflow_run_id, '12345')
  assert.equal(manifest.sizes.subpackages.admin > 0, true)
  assert.equal(manifest.files.some((file) => file.path === 'app.js'), true)

  const checksumPath = fixture.manifest.replace(/\.json$/, '.sha256')
  const expectedChecksum = createHash('sha256').update(manifestBytes).digest('hex')
  assert.equal(
    readFileSync(checksumPath, 'utf8'),
    `${expectedChecksum}  weapp-manifest.json\n`
  )
})

for (const [name, source, expectedError] of [
  ['placeholder origin', "const api = 'https://api.example.invalid'", 'placeholder Origin'],
  [
    'localhost origin',
    `const api = '${EXPECTED_ORIGIN}'; fetch('http://localhost:8000')`,
    'local HTTP Origin'
  ],
  [
    'source map marker',
    `const api = '${EXPECTED_ORIGIN}'\n//# sourceMappingURL=app.js.map`,
    'source map'
  ],
  [
    'H5 runtime marker',
    `const api = '${EXPECTED_ORIGIN}'; ` +
      "const marker = '@tarojs/components/dist-h5'",
    'H5-only marker'
  ],
  [
    'private key marker',
    `const api = '${EXPECTED_ORIGIN}'; const marker = '` +
      '-----BEGIN ' + 'PRIVATE KEY-----' + "'",
    'Secret marker'
  ]
]) {
  test(`rejects ${name}`, () => {
    const fixture = createFixture(source)

    const result = runChecker(fixture)

    assert.notEqual(result.status, 0)
    assert.match(result.stderr, new RegExp(expectedError, 'i'))
  })
}

test('rejects a source map file even when it is not referenced', () => {
  const fixture = createFixture()
  writeFileSync(join(fixture.artifactRoot, 'app.js.map'), '{}')

  const result = runChecker(fixture)

  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /source map/i)
})

test('rejects release eligibility for the reserved CI test origin', () => {
  const fixture = createFixture()

  const result = runChecker(fixture, { WEAPP_RELEASE_ELIGIBLE: '1' })

  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /reserved CI Origin/i)
})

test('rejects a main package above the frozen raw byte limit', () => {
  const fixture = createFixture()
  writeFileSync(join(fixture.artifactRoot, 'large.bin'), Buffer.alloc(2 * 1024 * 1024))

  const result = runChecker(fixture)

  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /main package exceeds/i)
})
