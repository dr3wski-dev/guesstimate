/* Local dev server: serves the built site/ AND the questions API, so the browser
   suites can exercise the real client against the real selection logic without a
   Workers runtime. It imports worker/src/selection.js directly — the same module
   the deployed Worker uses — so a divergence here would be a real divergence.

   node handoff/pipeline/devserver.mjs [port]
*/
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { roundsForDate, puzzleNumber, todayDateString, BAG_EPOCH } from '../worker/src/selection.js';
import POOL from '../data/questions.json' with { type: 'json' };
import SCHEDULE from '../data/schedule.json' with { type: 'json' };

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SITE = path.resolve(HERE, '../../site');
const PORT = Number(process.argv[2] || 8901);
const TYPES = { '.html':'text/html', '.json':'application/json', '.png':'image/png',
                '.woff2':'font/woff2', '.txt':'text/plain', '.xml':'application/xml' };

// Same contract as worker/src/index.js: a requested date is honored only if it is
// already in the past, so this can't be walked forward to read a future puzzle.
function sanitizeDate(raw, today){
  if(!raw || !/^\d{4}-\d{2}-\d{2}$/.test(raw)) return null;
  const t = Date.parse(raw + 'T00:00:00Z');
  if(!Number.isFinite(t)) return null;
  if(t < Date.parse(BAG_EPOCH + 'T00:00:00Z')) return null;
  if(t > Date.parse(today + 'T00:00:00Z')) return null;
  return raw;
}

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if(url.pathname === '/api/daily'){
    const today = todayDateString();
    const date = sanitizeDate(url.searchParams.get('d'), today) || today;
    const body = JSON.stringify({
      date, today, puzzleNumber: puzzleNumber(date),
      questions: roundsForDate(date, POOL, SCHEDULE),
    });
    res.writeHead(200, {'content-type':'application/json; charset=utf-8'});
    return res.end(body);
  }
  let file = path.join(SITE, url.pathname === '/' ? 'index.html' : url.pathname);
  if(!file.startsWith(SITE)) { res.writeHead(403); return res.end(); }
  fs.readFile(file, (err, data) => {
    if(err){ res.writeHead(404); return res.end('not found'); }
    res.writeHead(200, {'content-type': TYPES[path.extname(file)] || 'application/octet-stream'});
    res.end(data);
  });
}).listen(PORT, () => console.log(`dev server on http://localhost:${PORT} (site + /api/daily)`));
