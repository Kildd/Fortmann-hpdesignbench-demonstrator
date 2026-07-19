import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const src = path.join(root, 'engine')
const dest = path.join(root, 'public', 'engine')
const manifest = []
const bundle = {}

function copyDir(from, to, prefix = '') {
  fs.mkdirSync(to, { recursive: true })
  for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
    if (
      entry.name === '__pycache__' ||
      entry.name === '.venv' ||
      entry.name.endsWith('.pyc') ||
      entry.name === 'experiment.py' ||
      entry.name === 'problem_builder.py' ||
      entry.name === 'algorithms.py' ||
      entry.name === 'cache_eval.py'
    ) {
      continue
    }
    const a = path.join(from, entry.name)
    const b = path.join(to, entry.name)
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name
    if (entry.isDirectory()) copyDir(a, b, rel)
    else {
      const text = fs.readFileSync(a, 'utf8')
      fs.writeFileSync(b, text)
      const key = rel.replaceAll('\\', '/')
      manifest.push(key)
      bundle[key] = text
    }
  }
}

fs.rmSync(dest, { recursive: true, force: true })
copyDir(src, dest)
fs.writeFileSync(path.join(dest, 'manifest.json'), JSON.stringify(manifest, null, 2))
// Single download for the browser worker (avoids flaky multi-file Pages fetches).
fs.writeFileSync(path.join(dest, 'bundle.json'), JSON.stringify(bundle))
const bundleKb = Math.round(fs.statSync(path.join(dest, 'bundle.json')).size / 1024)
console.log(
  `Synced engine -> public/engine (${manifest.length} files, bundle ${bundleKb} KB)`,
)
