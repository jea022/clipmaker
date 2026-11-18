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
  checks.statusUnderClip = (await page.textContent('#msg-clip')).includes('Clip listo')
    && await page.$eval('#msg-clip', e => e.closest('section') === document.querySelector('#drop').closest('section'));
  await page.selectOption('#account', 'wganga');

  // a) cam_game (flujo original)
  const img = await page.$('#frame');
  await img.scrollIntoViewIfNeeded();
  const bb = await img.boundingBox();
  await page.mouse.move(bb.x + bb.width * 0.70, bb.y + bb.height * 0.02);
  await page.mouse.down();
  await page.mouse.move(bb.x + bb.width * 0.98, bb.y + bb.height * 0.34, { steps: 5 });
  await page.mouse.up();
  await page.fill('#title', 'Se le cae todo en pleno robo en GTA VI');
  await page.check('#people input[value="westcol"]');
  await page.check('#people input[value="samulx"]');
  checks.camGameEnabled = await page.$eval('#go', b => !b.disabled);
  checks.camToolEnabledForCamGame = !(await page.$eval('#toolcam-lbl', e => e.classList.contains('off')));
  const v1 = await render();
  checks.camGameVideo = v1[0] === 1080 && v1[1] === 1920;
  const caps = await page.$$eval('.cap', els => els.map(e => e.textContent));
  checks.caps = caps.length === 3 && caps[0].includes('#westcol') && caps[0].includes('#samulx');

  // b) video arriba + imagen abajo
  await page.check('input[value="clip_image"]', { force: true });
  checks.imageZoneShown = await visible('#extra-image');
  checks.clipbZoneHidden = !(await visible('#extra-clipb'));
  checks.camToolDisabledForImage = (await page.$eval('#toolcam-lbl', e => e.classList.contains('off'))) && (await page.$eval('#toolgame', e => e.checked));
  checks.goBlockedWithoutImage = await page.$eval('#go', b => b.disabled);
  checks.hintMentionsImage = (await page.textContent('#gohint')).includes('imagen');
  await page.setInputFiles('#file-image', image);
  await page.waitForSelector('#drop-image img');
  checks.extraStatusUnderVariation = await page.$eval('#msg-extra', e => !!e.closest('section').querySelector('#presets'));
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

  // g) controles de texto, recorte de gameplay, vista previa y guardado
  await page.check('input[value="cam_game"]', { force: true });
  await page.waitForFunction(() => document.querySelector('#preview').naturalWidth === 1080, null, { timeout: 20000 });
  checks.previewShown = (await page.$eval('#preview', e => e.naturalHeight)) === 1920;
  const prev0 = await page.$eval('#preview', e => e.src);
  await page.evaluate(() => { for (const [id, v] of [['titleh', 480], ['fsize', 120]]) { const el = document.getElementById(id); el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); } });
  checks.slidersLabels = (await page.textContent('#titleh-out')) === '480 px' && (await page.textContent('#fsize-out')) === '120';
  await page.waitForFunction(p => document.querySelector('#preview').src !== p, prev0, { timeout: 20000 });
  checks.previewUpdatesWithSliders = true;
  await page.check('#toolgame', { force: true });
  const frameEl = await page.$('#frame');
  await frameEl.scrollIntoViewIfNeeded();
  const bb2 = await frameEl.boundingBox();
  const prev1 = await page.$eval('#preview', e => e.src);
  await page.mouse.move(bb2.x + bb2.width * 0.05, bb2.y + bb2.height * 0.30);
  await page.mouse.down();
  await page.mouse.move(bb2.x + bb2.width * 0.65, bb2.y + bb2.height * 0.95, { steps: 5 });
  await page.mouse.up();
  const gw = await page.$eval('#gbox', e => parseFloat(e.style.width));
  checks.gameBoxDrawn = gw > 55 && gw < 65;
  await page.waitForFunction(p => document.querySelector('#preview').src !== p, prev1, { timeout: 20000 });
  checks.previewUpdatesWithGameBox = true;
  const v6 = await render();
  checks.renderWithNewControls = v6[0] === 1080 && v6[1] === 1920;
  await page.click('#resetgame');
  checks.gameBoxReset = (await page.$eval('#gbox', e => parseFloat(e.style.width))) === 100;
  // estilos y tipografias del texto
  checks.sixStyles = (await page.$$('#styles .opt')).length === 6;
  checks.sevenFonts = (await page.$$('#fonts .opt')).length === 7;
  checks.bandControlsInBand = (await visible('#grp-band')) && !(await visible('#grp-split')) && !(await visible('#grp-offset'));
  const change = async fn => {
    const before = await page.$eval('#preview', e => e.src);
    await fn();
    await page.waitForFunction(p => document.querySelector('#preview').src !== p, before, { timeout: 20000 });
    return true;
  };
  checks.previewChangesWithStyle = await change(() => page.check('input[name=tstyle][value=box_white]', { force: true }));
  checks.fsizeRecommended = (await page.$eval('#fsize', e => e.value)) === '56';
  checks.overlayControls = !(await visible('#grp-band')) && (await visible('#grp-split')) && (await visible('#grp-offset'));
  checks.previewChangesWithFont = await change(() => page.check('input[name=tfont][value=anton]', { force: true }));
  checks.previewChangesWithSplitOffset = await change(() => page.evaluate(() => {
    for (const [id, v] of [['split', 40], ['offset', 100]]) { const el = document.getElementById(id); el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); }
  }));
  checks.overlayLabels = (await page.textContent('#split-out')) === '40 %' && (await page.textContent('#offset-out')) === '+100 px';
  checks.previewChangesWithUppercase = await change(() => page.uncheck('#upper'));
  await page.check('input[value="clip_blur"]', { force: true });
  checks.blurHidesSplit = !(await visible('#grp-split')) && (await visible('#grp-offset'));
  await page.check('input[value="cam_game"]', { force: true });
  checks.splitBackForStacked = await visible('#grp-split');
  const v7 = await render();
  checks.renderOverlayStyle = v7[0] === 1080 && v7[1] === 1920;
  await page.screenshot({ path: shot.replace('.png', '_overlay.png'), fullPage: true });
  await page.click('#savecam');
  await page.waitForFunction(() => /Guardado/.test(document.querySelector('#savemsg').textContent));
  checks.savedMessage = true;
  await page.screenshot({ path: shot, fullPage: true });

  // h) lo guardado sobrevive a recargar la pagina; fabrica lo restablece
  await page.reload();
  await page.waitForSelector('#presets .card');
  await page.waitForFunction(() => document.querySelector('#account option'));
  await page.selectOption('#account', 'wganga');
  await page.waitForFunction(() => document.querySelector('#titleh').value === '480');
  checks.savedSurvivesReload = (await page.$eval('#fsize', e => e.value)) === '56' && (await page.textContent('#titleh-out')) === '480 px';
  const camW = await page.$eval('#box', e => parseFloat(e.style.width));
  checks.savedCamBoxSurvivesReload = camW > 26 && camW < 30;
  checks.styleSurvivesReload = (await page.$eval('input[name=tstyle]:checked', e => e.value)) === 'box_white';
  checks.fontSurvivesReload = (await page.$eval('input[name=tfont]:checked', e => e.value)) === 'anton';
  checks.splitOffsetUppercaseSurvive = (await page.$eval('#split', e => e.value)) === '40' && (await page.$eval('#offset', e => e.value)) === '100' && !(await page.$eval('#upper', e => e.checked));
  checks.overlayControlsAfterReload = !(await visible('#grp-band')) && (await visible('#grp-split'));
  await page.click('#factory');
  await page.waitForFunction(() => document.querySelector('#titleh').value === '320');
  checks.factoryRestores = (await page.$eval('#fsize', e => e.value)) === '96';
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#account option'));
  await page.selectOption('#account', 'wganga');
  checks.factoryPersists = (await page.$eval('#titleh', e => e.value)) === '320';
  checks.factoryRestoresText = (await page.$eval('input[name=tstyle]:checked', e => e.value)) === 'band'
    && (await page.$eval('input[name=tfont]:checked', e => e.value)) === 'inter'
    && (await page.$eval('#upper', e => e.checked)) && (await visible('#grp-band'));

  // i) editor de hashtags
  const val = sel => page.$eval(sel, e => e.value);
  await page.waitForFunction(() => document.querySelector('#ht-always').value !== '');
  checks.hashFormLoaded = (await val('#ht-always')) === '#GTA6 #GTAVI' && (await val('#ht-people')).includes('westcol: #westcol #westcolclips');
  checks.hashCounts = (await val('#ht-count-tiktok')) === '5' && (await val('#ht-count-shorts')) === '3' && await page.$eval('#ht-shorts-tag', e => e.checked);
  checks.hashStatusRecommended = (await page.textContent('#ht-msg')).includes('recomendada');
  await page.selectOption('#account', 'gtahispa');
  checks.hashOtherAccount = (await val('#ht-niche')).includes('#gta6clips') && (await val('#ht-people')).includes('illojuan') && !(await val('#ht-people')).includes('westcol');
  await page.selectOption('#account', 'wganga');
  await page.click('#hashsec summary');
  await page.click('#ht-preview');
  await page.waitForFunction(() => document.querySelectorAll('#ht-samples .sample-cap').length === 6);
  const samples = await page.$$eval('#ht-samples .sample-cap', els => els.map(e => e.textContent));
  checks.hashSixSamples = samples.every(s => (s.match(/#/g) || []).length === 5) && new Set(samples).size === 6;
  checks.hashUsageShown = (await page.$$('#ht-usage span')).length >= 8 && (await page.textContent('#ht-usage span')).includes('×30');
  await page.selectOption('#clipgame', 'gta5rp');
  checks.hashGameClearsSamples = (await page.$$('#ht-samples .sample-cap')).length === 0;
  await page.click('#ht-preview');
  await page.waitForFunction(() => document.querySelectorAll('#ht-samples .sample-cap').length === 6);
  const rpTxt = (await page.$$eval('#ht-samples .sample-cap', els => els.map(e => e.textContent))).join(' ');
  checks.hashRpGame = !rpTxt.includes('#GTA6') && rpTxt.includes('#gtaroleplay');
  await page.selectOption('#clipgame', 'gta6');
  await page.fill('#ht-niche', '#aaa1 #bbb1 #ccc1');
  await page.fill('#ht-people', (await val('#ht-people')) + '\nana: #ana1 #ana2');
  await page.click('#ht-save');
  await page.waitForFunction(() => /guardados/.test(document.querySelector('#ht-msg').textContent));
  checks.hashSaved = (await page.$eval('#ht-msg', e => e.className)).includes('ok') && (await page.textContent('#ht-msg')).length > 0;
  checks.hashNewPersonChip = (await page.$$('#people input[value="ana"]')).length === 1;
  await page.fill('#ht-niche', '#ho!la');
  await page.click('#ht-save');
  await page.waitForFunction(() => /no válido/i.test(document.querySelector('#ht-msg').textContent));
  checks.hashInvalidRejected = (await page.$eval('#ht-msg', e => e.className)).includes('err') && (await page.$$('#people input[value="ana"]')).length === 1;
  await page.fill('#ht-niche', '#aaa1 #bbb1 #ccc1');
  await page.fill('#ht-people', 'sin dos puntos');
  await page.click('#ht-save');
  await page.waitForFunction(() => /Falta/.test(document.querySelector('#ht-msg').textContent));
  checks.hashPeopleLineRejected = true;
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#account option'));
  await page.selectOption('#account', 'wganga');
  await page.waitForFunction(() => document.querySelector('#ht-niche').value !== '');
  checks.hashSavedSurvivesReload = (await val('#ht-niche')) === '#aaa1 #bbb1 #ccc1' && (await page.$$('#people input[value="ana"]')).length === 1
    && (await page.textContent('#ht-msg')).includes('personalizada');
  await page.click('#hashsec summary');
  await page.click('#ht-reset');
  await page.waitForFunction(() => /recomendados/.test(document.querySelector('#ht-msg').textContent));
  checks.hashResetWorks = (await val('#ht-niche')).includes('#kick') && (await page.$$('#people input[value="ana"]')).length === 0
    && (await page.textContent('#ht-msg')).includes('restablecieron');
  await browser.close();

  const failed = Object.entries(checks).filter(([, v]) => v !== true).map(([k]) => k);
  console.log(JSON.stringify({ checks, errors }, null, 2));
  const unexpected = errors.filter(e => !/status of 400/.test(e));
  const expected400 = errors.length - unexpected.length;
  const ok = failed.length === 0 && unexpected.length === 0 && expected400 <= 1;
  console.log(ok ? 'UI PASS' : `UI FAIL: ${failed.join(', ')}`);
  process.exit(ok ? 0 : 1);
})();
