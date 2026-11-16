import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:4317';
const videoDir = new URL('../../artifacts/walkthrough/', import.meta.url);
const output = new URL('../../docs/', import.meta.url);
await mkdir(videoDir, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : process.platform === 'win32' ? { channel: 'msedge' } : {}) });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', recordVideo: { dir: fileURLToPath(videoDir), size: { width: 1440, height: 1000 } } });
const page = await context.newPage();
const started = performance.now();
const captions = [];
const elapsed = () => (performance.now() - started) / 1000;
async function caption(text) {
  captions.push({ start: elapsed(), text });
  await page.evaluate(text => {
    let overlay = document.getElementById('walkthrough-caption');
    if (!overlay) {
      overlay = document.createElement('div'); overlay.id = 'walkthrough-caption';
      overlay.style.cssText = 'position:fixed;z-index:99999;bottom:22px;left:50%;transform:translateX(-50%);max-width:1000px;width:max-content;padding:16px 26px;background:rgba(23,47,40,.97);color:#fff;border:1px solid #61796f;border-radius:8px;font:17px/1.55 system-ui;text-align:center;box-shadow:0 6px 30px #0002;pointer-events:none';
      document.body.append(overlay);
    }
    overlay.textContent = text;
  }, text);
}
async function holdUntil(seconds) { const remaining = seconds - elapsed(); if (remaining > 0) await page.waitForTimeout(remaining * 1000); }
function timestamp(seconds) { return new Date(seconds * 1000).toISOString().slice(11, 23); }
try {
  await page.goto(base);
  await page.waitForFunction(() => !document.querySelector('button.button.primary')?.disabled);
  await caption('QueryProof reviews SQL against an explicit metric definition. This is the real local application, using fictional commerce data.');
  await holdUntil(8);

  await page.getByRole('button', { name: 'Run review', exact: true }).click();
  await page.getByRole('heading', { name: 'This number needs a closer look.' }).waitFor();
  await page.locator('.result-panel').scrollIntoViewIfNeeded();
  await page.locator('.result-panel').evaluate(element => element.scrollIntoView({ block: 'start' }));
  await caption('The query reports 1,110 USD. The independent row calculation gives 400 USD. These values were calculated from this snapshot.');
  await holdUntil(17);

  await page.locator('.finding').first().evaluate(element => element.scrollIntoView({ block: 'start' }));
  await caption('Three orders contribute more than once. Each finding includes the contract clause, a reproducible diagnostic query, and bounded example rows.');
  await holdUntil(26);

  await page.getByRole('button', { name: 'Inspect suggested repair' }).click();
  await page.locator('.revision-panel').evaluate(element => element.scrollIntoView({ block: 'start' }));
  await caption('Inspect the original and proposed SQL side by side. This deterministic suggestion preserves the metric definition; it has not been accepted.');
  await holdUntil(35);

  await page.getByRole('button', { name: 'Check revision', exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent.includes('Accept checked revision') && !button.disabled));
  await page.locator('.candidate-summary').evaluate(element => element.scrollIntoView({ block: 'start' }));
  await caption('The revision executes against the same snapshot. Its total is 400 USD, all checks pass, and the intended population is preserved.');
  await holdUntil(44);

  await page.getByRole('button', { name: 'Accept checked revision' }).click();
  await page.locator('.result-panel').evaluate(element => element.scrollIntoView({ block: 'start' }));
  await caption('Only a checked revision can be accepted. The original review remains in history. Passing is conditional on this contract and snapshot.');
  await holdUntil(53);

  await page.locator('.export-panel').evaluate(element => element.scrollIntoView({ block: 'center' }));
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'HTML report' }).click();
  await download;
  await caption('Export a readable HTML report or JSON evidence packet. Raw input rows are excluded; finding examples require an explicit choice.');
  await holdUntil(62);

  await page.getByRole('button', { name: /^History/ }).click();
  await page.locator('.history-panel').evaluate(element => element.scrollIntoView({ block: 'start' }));
  await caption('Saved reviews retain their SQL, contract, snapshot identity, and findings. Optional live-model assistance is separate from deterministic evidence.');
  await holdUntil(72);
  const workflowDuration = elapsed();
  await context.close();
  await page.video().saveAs(fileURLToPath(new URL('walkthrough.webm', output)));
  const playbackContext = await browser.newContext();
  const playback = await playbackContext.newPage();
  await playback.goto(new URL('walkthrough.webm', output).href);
  await playback.waitForFunction(() => document.querySelector('video')?.duration > 0);
  const media = await playback.locator('video').evaluate(video => ({ duration: video.duration, width: video.videoWidth, height: video.videoHeight }));
  const duration = media.duration;
  assert(duration >= 60 && duration <= 90, `Expected a 60–90 second walkthrough; recorded ${duration} seconds`);
  await playbackContext.close();
  const vtt = 'WEBVTT\n\n' + captions.map((item, index) => `${index + 1}\n${timestamp(item.start)} --> ${timestamp(captions[index + 1]?.start ?? duration)}\n${item.text}\n`).join('\n');
  await writeFile(new URL('walkthrough.vtt', output), vtt);
  await writeFile(new URL('walkthrough-capture.json', output), JSON.stringify({ captured_at: new Date().toISOString(), duration_seconds: duration, workflow_wall_seconds: workflowDuration, media, browser: browser.version(), platform: process.platform, base, mode: 'Recorded real deterministic workflow; captions overlaid during capture', captions }, null, 2) + '\n');
  process.stdout.write(`Recorded ${duration.toFixed(1)} seconds to docs/walkthrough.webm with embedded captions and WebVTT.\n`);
} finally { await browser.close(); }
