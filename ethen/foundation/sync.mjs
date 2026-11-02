import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'

const revision = '0f640c0826fb34347fc9b4a72f9282a33f5e5270'
const source = new URL('./ethen.tokens.json', import.meta.url)
const destination = new URL('../../apps/shared/src/ethen-foundation.ts', import.meta.url)
const bytes = readFileSync(source)
const sha = createHash('sha256').update(bytes).digest('hex')
const tokens = JSON.parse(bytes.toString('utf8'))
const generated = `/** Generated from Ethen Foundation tokens/ethen.tokens.json at ${revision}.
 * Source SHA-256: ${sha}. Preserve canonical token values; see ethen/foundation/README.md.
 */
export const ETHEN_FOUNDATION = ${JSON.stringify(tokens, null, 2)} as const
`
const mode = process.argv[2] ?? '--check'
if (mode === '--write') {
  writeFileSync(destination, generated)
} else if (mode === '--check') {
  if (readFileSync(destination, 'utf8') !== generated) throw new Error('Foundation export differs: review the pinned snapshot, then run sync.mjs --write')
} else {
  throw new Error('Use --check or --write')
}
console.log(`Foundation ${tokens.version} ${sha}: ${mode}`)
