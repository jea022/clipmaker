// Cierre real desde el navegador: arranca su propia copia de la app, acepta el aviso y comprueba que se apaga.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const net = require('net');
const path = require('path');

const freePort = () => new Promise(res => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });
const alive = async port => { try { const r = await fetch(`http://127.0.0.1:${port}/api/ping`); return r.ok; } catch { return false; } };
const wait = async (fn, ms = 30000) => { const end = Date.now() + ms; while (Date.now() < end) { if (await fn()) return true; await new Promise(r => setTimeout(r, 300)); } return false; };

(async () => {
  const port = await freePort();
  const py = path.join(__dirname, '.venv', 'bin', 'python');
  const app = spawn(py, [path.join(__dirname, 'app.py'), String(port)], { cwd: __dirname, stdio: 'ignore' });
  const exited = new Promise(res => app.on('exit', code => res(code)));
  const checks = {};
  checks.started = await wait(() => alive(port));
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(`http://127.0.0.1:${port}`);
  await page.waitForSelector('#presets .card');
  let asked = '';
  page.once('dialog', d => { asked = d.message(); d.accept(); });
  await page.click('#quit');
  await page.waitForFunction(() => /Clipmaker se cerró/.test(document.body.textContent), null, { timeout: 10000 });
  checks.askedBeforeClosing = asked.includes('Cerrar Clipmaker');
  checks.pageShowsClosedMessage = (await page.textContent('body')).includes('Ya puedes cerrar esta pestaña');
  checks.noMoreButtons = (await page.$$('button')).length === 0;
  checks.processExited = (await Promise.race([exited, new Promise(r => setTimeout(() => r('colgado'), 10000))])) === 0;
  checks.portClosed = await wait(async () => !(await alive(port)), 5000);
  await browser.close();
  if (app.exitCode === null) app.kill();
  const failed = Object.entries(checks).filter(([, v]) => v !== true).map(([k]) => k);
  console.log(JSON.stringify({ checks, errors }, null, 2));
  const ok = failed.length === 0 && errors.length === 0;
  console.log(ok ? 'QUIT PASS' : `QUIT FAIL: ${failed.join(', ')}`);
  process.exit(ok ? 0 : 1);
})();
