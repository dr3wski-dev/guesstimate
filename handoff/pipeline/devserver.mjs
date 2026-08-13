/* Local dev server: serves the built site/ AND the questions API, so the browser
   suites exercise the real client against the real server code.

   WHY IT DELEGATES INSTEAD OF REIMPLEMENTING
   This used to answer /api/daily itself — its own date sanitiser, its own response
   shape, its own headers. It was a second implementation of the Worker wearing a
   comment claiming it couldn't diverge, and it had already diverged: no
   x-content-type-options, no 405 on a POST, no cache-control. A security probe run
   against it reported two failures that were not real, which is the more expensive
   kind of wrong — a harness that lies in the safe direction gets trusted.

   Now it calls the Worker's own fetch handler. The Workers runtime globals it needs
   (Request, Response, URL) are standard in Node 18+; `caches` is absent, which the
   Worker already handles since it guards on `globalThis.caches?.default`.

   IT ALSO APPLIES THE REAL CSP
   site/_headers is enforced by Pages in production and by nothing locally, so the
   suites were passing under a policy far looser than the deployed one and a
   violation would only have surfaced after deploy. The headers block is parsed and
   applied here so local runs fail the same way production would.

   node handoff/pipeline/devserver.mjs [port]
*/
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import worker from '../worker/src/index.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SITE = path.resolve(HERE, '../../site');
const PORT = Number(process.argv[2] || 8901);
const TYPES = { '.html':'text/html', '.json':'application/json', '.png':'image/png',
                '.woff2':'font/woff2', '.txt':'text/plain', '.xml':'application/xml' };

/* Parse site/_headers well enough to reproduce production locally. Pages' format is
   a path pattern on column 0 followed by indented `Name: value` lines. Only the
   globs this project actually uses are supported — a general implementation would
   be a second source of truth about something Pages already owns. */
function loadHeaders(){
  const f = path.join(SITE, '_headers');
  if(!fs.existsSync(f)) return [];
  const rules = []; let cur = null;
  for(const line of fs.readFileSync(f, 'utf8').split('\n')){
    if(!line.trim()) continue;
    if(!/^\s/.test(line)){
      cur = { pattern: line.trim(), headers: {} };
      rules.push(cur);
    }else if(cur){
      const i = line.indexOf(':');
      if(i > 0) cur.headers[line.slice(0, i).trim().toLowerCase()] = line.slice(i + 1).trim();
    }
  }
  return rules;
}
const RULES = loadHeaders();
function headersFor(pathname){
  const out = {};
  for(const r of RULES){
    const re = new RegExp('^' + r.pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*') + '$');
    if(re.test(pathname)) Object.assign(out, r.headers);
  }
  // Strict-Transport-Security is meaningless (and ignored) over plain http, and
  // setting it locally would only teach the browser something wrong about localhost.
  delete out['strict-transport-security'];
  return out;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  if(url.pathname.startsWith('/api/')){
    const request = new Request(url, { method: req.method });
    const wres = await worker.fetch(request, {}, { waitUntil(){} });
    const body = Buffer.from(await wres.arrayBuffer());
    const h = {};
    wres.headers.forEach((v, k) => { h[k] = v; });
    res.writeHead(wres.status, h);
    return res.end(body);
  }

  let file = path.join(SITE, url.pathname === '/' ? 'index.html' : url.pathname);
  if(!file.startsWith(SITE)) { res.writeHead(403); return res.end(); }
  fs.readFile(file, (err, data) => {
    if(err){ res.writeHead(404); return res.end('not found'); }
    res.writeHead(200, {
      'content-type': TYPES[path.extname(file)] || 'application/octet-stream',
      ...headersFor(url.pathname),
    });
    res.end(data);
  });
});

server.listen(PORT, () => {
  const csp = headersFor('/index.html')['content-security-policy'];
  console.log(`dev server on http://localhost:${PORT} (site + real Worker at /api/*)`);
  console.log(csp ? '  CSP enforced from site/_headers' : '  NO CSP — run build_site.py first');
});
