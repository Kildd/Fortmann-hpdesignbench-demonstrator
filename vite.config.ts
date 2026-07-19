import { defineConfig, type Plugin } from 'vite'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'

function optimizeApiPlugin(): Plugin {
  return {
    name: 'hp-optimize-api',
    configureServer(server) {
      server.middlewares.use('/api/optimize', (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405
          res.end('Method Not Allowed')
          return
        }

        const chunks: Buffer[] = []
        req.on('data', (c) => chunks.push(c))
        req.on('end', () => {
          let body: Record<string, unknown> = {}
          try {
            body = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')
          } catch {
            res.statusCode = 400
            res.end('Invalid JSON')
            return
          }

          const root = server.config.root
          const py =
            process.env.HP_DEMO_PYTHON ||
            path.join(root, '.venv', 'Scripts', 'python.exe')
          const script = path.join(root, 'engine', 'demo_optimize.py')
          if (!fs.existsSync(py) || !fs.existsSync(script)) {
            res.statusCode = 503
            res.setHeader('Content-Type', 'application/json')
            res.end(
              JSON.stringify({
                type: 'error',
                message:
                  'Python-Engine nicht gefunden. Bitte .venv anlegen und engine/requirements-engine.txt installieren.',
              }),
            )
            return
          }

          const args = [
            script,
            '--n-trials',
            String(body.nTrials ?? 60),
            '--omega-gwp',
            String(body.omegaGwp ?? 1),
            '--omega-cost',
            String(body.omegaCost ?? 0),
            '--seed',
            String(body.seed ?? 42),
          ]
          if (body.spanMm != null) {
            args.push('--span-mm', String(body.spanMm))
          }
          if (body.loadCategory) {
            args.push('--load-category', String(body.loadCategory))
          }

          res.writeHead(200, {
            'Content-Type': 'application/x-ndjson; charset=utf-8',
            'Cache-Control': 'no-cache',
            Connection: 'keep-alive',
          })

          const child: ChildProcessWithoutNullStreams = spawn(py, args, {
            cwd: root,
            env: { ...process.env, PYTHONUNBUFFERED: '1' },
          })

          let stderr = ''
          child.on('error', (err) => {
            if (!res.headersSent) {
              res.writeHead(500, { 'Content-Type': 'application/json' })
            }
            res.end(
              JSON.stringify({
                type: 'error',
                message: `Python-Start fehlgeschlagen: ${err.message}`,
              }) + '\n',
            )
          })
          child.stdout.on('data', (d: Buffer) => {
            res.write(d)
          })
          child.stderr.on('data', (d: Buffer) => {
            stderr += d.toString('utf8')
          })
          child.on('close', (code) => {
            if (code && code !== 0) {
              res.write(
                JSON.stringify({
                  type: 'error',
                  message: (stderr || `Python exit ${code}`).slice(0, 2000),
                }) + '\n',
              )
            }
            res.end()
          })
          // Only kill the optimizer if the *response* is aborted by the client.
          // Listening on req 'close' would kill the child as soon as the POST body ends.
          res.on('close', () => {
            if (!res.writableFinished && !child.killed) child.kill()
          })
        })
      })
    },
  }
}

export default defineConfig(({ command }) => ({
  // Project Pages URL in production; root path for local `vite` / `vite preview`.
  base:
    command === 'build' ? '/Fortmann-hpdesignbench-demonstrator/' : '/',
  plugins: [optimizeApiPlugin()],
  server: {
    port: 5173,
  },
  publicDir: 'public',
  worker: {
    format: 'es',
  },
}))
