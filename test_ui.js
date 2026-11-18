const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const base = process.argv[2] || 'http://127.0.0.1:5055';
  const clip = process.argv[3] || path.join(__dirname, 'out', 'sample.mp4');
  const shot = process.argv[4] || path.join(__dirname, 'out', 'ui.png');
  const image = path.join(__dirname, 'out', 'test_image.jpg');
  const clipB = path.join(__dirname, 'out', 'clip_b.mp4');
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => m.type() === 'error' && errors.push(m.text()));
  const checks = {};

  const render = async () => {
    const prev = await page.$eval('#result video', v => v.getAttribute('src')).catch(() => null);
    await page.click('#go');
    await page.waitForFunction(p => {
      const v = document.querySelector('#result video');
      return v && v.getAttribute('src') !== p;
    }, prev, { timeout: 60000 });
    return page.$eval('#result video', v => new Promise(r => {
      const done = () => r([v.videoWidth, v.videoHeight, Math.round(v.duration)]);
      if (v.readyState >= 1) return done();
      v.onloadedmetadata = done; v.onerror = () => r(['error']);
    }));
  };
  const visible = sel => page.$eval(sel, e => getComputedStyle(e).display !== 'none');

  await page.goto(base);
  await page.waitForSelector('#account option', { state: 'attached' });
  await page.waitForSelector('#presets .card');
  checks.sixPresets = (await page.$$('#presets .card')).length === 6;
  checks.defaultIsCamGame = await page.$eval('input[value="cam_game"]', i => i.checked);
  checks.goDisabledAtStart = await page.$eval('#go', b => b.disabled);
  checks.hintAtStart = (await page.textContent('#gohint')).includes('clip principal');

  await page.setInputFiles('#file', clip);
  await page.waitForSelector('#stage', { state: 'visible' });
  await page.waitForFunction(() => document.querySelector('#frame').naturalWidth > 0);
  await page.selectOption('#account', 'wganga');

  // a) cam_game (flujo original)
  const img = await page.$('#frame');
  const bb = await img.boundingBox();
  await page.mouse.move(bb.x + bb.width * 0.70, bb.y + bb.height * 0.02);
  await page.mouse.down();
  await page.mouse.move(bb.x + bb.width * 0.98, bb.y + bb.height * 0.34, { steps: 5 });
  await page.mouse.up();
  await page.fill('#title', 'Se le cae todo en pleno robo en GTA VI');
  await page.check('#people input[value="westcol"]');
  await page.check('#people input[value="samulx"]');
  checks.camGameEnabled = await page.$eval('#go', b => !b.disabled);
  checks.camSectionVisible = await visible('#camsec');
  const v1 = await render();
  checks.camGameVideo = v1[0] === 1080 && v1[1] === 1920;
  const caps = await page.$$eval('.cap', els => els.map(e => e.textContent));
  checks.caps = caps.length === 3 && caps[0].includes('#westcol') && caps[0].includes('#samulx');

  // b) video arriba + imagen abajo
  await page.check('input[value="clip_image"]', { force: true });
  checks.imageZoneShown = await visible('#extra-image');
  checks.clipbZoneHidden = !(await visible('#extra-clipb'));
  checks.camHiddenForImage = !(await visible('#camsec'));
  checks.goBlockedWithoutImage = await page.$eval('#go', b => b.disabled);
  checks.hintMentionsImage = (await page.textContent('#gohint')).includes('imagen');
  await page.setInputFiles('#file-image', image);
  await page.waitForSelector('#drop-image img');
  checks.goEnabledWithImage = await page.waitForFunction(() => !document.querySelector('#go').disabled).then(() => true);
  const v2 = await render();
  checks.clipImageVideo = v2[0] === 1080 && v2[1] === 1920;

  // c) imagen arriba + video abajo reutiliza la misma imagen
  await page.check('input[value="image_clip"]', { force: true });
  checks.imageStillAttached = await page.$eval('#go', b => !b.disabled);
  const v3 = await render();
  checks.imageClipVideo = v3[0] === 1080 && v3[1] === 1920;

  // d) dos videos
  await page.check('input[value="clip_clip"]', { force: true });
  checks.clipbZoneShown = await visible('#extra-clipb');
  checks.imageZoneHidden = !(await visible('#extra-image'));
  checks.goBlockedWithoutB = await page.$eval('#go', b => b.disabled);
  checks.hintMentionsB = (await page.textContent('#gohint')).includes('segundo video');
  await page.setInputFiles('#file-clipb', clipB);
  await page.waitForSelector('#drop-clipb img');
  await page.selectOption('#audio', 'b');
  const v4 = await render();
  checks.clipClipVideo = v4[0] === 1080 && v4[1] === 1920;

  // e) fondo difuminado
  await page.check('input[value="clip_blur"]', { force: true });
  checks.noExtrasForBlur = !(await visible('#extra-image')) && !(await visible('#extra-clipb'));
  const v5 = await render();
  checks.blurVideo = v5[0] === 1080 && v5[1] === 1920;

  // f) cambiar de clip principal conserva la imagen adjunta
  await page.check('input[value="clip_image"]', { force: true });
  await page.setInputFiles('#file', clip);
  await page.waitForFunction(() => !document.querySelector('#go').disabled, null, { timeout: 15000 });
  checks.extrasSurviveNewClip = true;

  await page.screenshot({ path: shot, fullPage: true });
  await browser.close();

  const failed = Object.entries(checks).filter(([, v]) => v !== true).map(([k]) => k);
  console.log(JSON.stringify({ checks, errors }, null, 2));
  const ok = failed.length === 0 && errors.length === 0;
  console.log(ok ? 'UI PASS' : `UI FAIL: ${failed.join(', ')}`);
  process.exit(ok ? 0 : 1);
})();
