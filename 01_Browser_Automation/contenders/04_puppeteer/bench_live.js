/**
 * Live website benchmark for Puppeteer: Google Search & YouTube.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import puppeteer from 'puppeteer-core';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '../../');

function findChromeExecutable() {
  const candidates = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    path.join(process.env.USERPROFILE || '', 'AppData\\Local\\Google\\Chrome\\Application\\chrome.exe'),
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  throw new Error('Chrome executable not found on system.');
}

async function runLiveBenchmark({ headed = false } = {}) {
  const exe = findChromeExecutable();
  console.log(`\n[Puppeteer Live] Launching Chrome (headed=${headed})...`);

  const browser = await puppeteer.launch({
    executablePath: exe,
    headless: !headed,
    defaultViewport: { width: 1280, height: 800 },
    args: ['--window-size=1280,800']
  });
  const page = await browser.newPage();

  const results = {
    contender: 'puppeteer',
    environment: 'live',
    headed,
    google_search: {},
    youtube: {},
    success: false
  };

  try {
    // ==============================================================
    // Task 1: Google Search
    // ==============================================================
    console.log('\n[Puppeteer Live] Task 1: Google Search Pipeline...');
    const t0G = performance.now();
    await page.goto('https://www.google.com', { waitUntil: 'domcontentloaded' });
    const navGMs = performance.now() - t0G;

    // Dismiss cookies banner
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const acceptBtn = btns.find(b => b.textContent.includes('Accept all') || b.textContent.includes('I agree'));
      if (acceptBtn) acceptBtn.click();
    });
    await new Promise(r => setTimeout(r, 500));

    // Type query
    const searchSelector = "textarea[name='q'], input[name='q']";
    await page.waitForSelector(searchSelector, { timeout: 8000 });
    const t0Type = performance.now();
    await page.type(searchSelector, 'browser automation speed benchmark', { delay: 0 });
    await page.keyboard.press('Enter');
    const typeGMs = performance.now() - t0Type;

    // Wait for results
    const t0Wait = performance.now();
    let organicResults = [];
    try {
      await page.waitForSelector('#search h3, #rso h3, div.g h3', { timeout: 6000 });
      organicResults = await page.evaluate(() => {
        const items = Array.from(document.querySelectorAll('#search h3, #rso h3, div.g h3')).slice(0, 5);
        return items.map(h => ({
          title: h.textContent.trim(),
          link: h.closest('a') ? h.closest('a').href : ''
        }));
      });
    } catch (e) {
      // Bot detection or consent gate
    }
    const waitGMs = performance.now() - t0Wait;

    const totalGMs = performance.now() - t0G;

    results.google_search = {
      nav_ms: Number(navGMs.toFixed(2)),
      type_ms: Number(typeGMs.toFixed(2)),
      wait_results_ms: Number(waitGMs.toFixed(2)),
      total_ms: Number(totalGMs.toFixed(2)),
      results_count: organicResults.length,
      success: organicResults.length > 0,
      top_result: organicResults[0]?.title || null
    };
    console.log(`  Google Search completed in ${totalGMs.toFixed(1)}ms. Top result: ${results.google_search.top_result}`);

    // ==============================================================
    // Task 2: YouTube Search & Video Interaction
    // ==============================================================
    console.log('\n[Puppeteer Live] Task 2: YouTube Search & Video Interaction...');
    const t0Y = performance.now();
    await page.goto('https://www.youtube.com', { waitUntil: 'domcontentloaded' });
    const navYMs = performance.now() - t0Y;

    // Dismiss consent popup
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const consent = btns.find(b => b.textContent.includes('Accept all') || b.textContent.includes('Reject all'));
      if (consent) consent.click();
    });
    await new Promise(r => setTimeout(r, 1000));

    // Search box
    const ytInputSel = "input#search, input[name='search_query']";
    await page.waitForSelector(ytInputSel, { timeout: 10000 });
    const t0YType = performance.now();
    await page.type(ytInputSel, 'lofi coding music', { delay: 0 });
    await page.keyboard.press('Enter');
    const typeYMs = performance.now() - t0YType;

    // Wait for video result
    const t0YResults = performance.now();
    await page.waitForSelector('ytd-video-renderer #video-title', { timeout: 15000 });
    const waitYResultsMs = performance.now() - t0YResults;

    const firstVideoTitle = await page.$eval('ytd-video-renderer #video-title', el => el.textContent.trim());

    // Click first video
    await page.click('ytd-video-renderer #video-title');

    // Wait for player ready
    const t0Player = performance.now();
    await page.waitForSelector('video.html5-main-video', { timeout: 15000 });
    await page.waitForFunction(() => {
      const video = document.querySelector('video.html5-main-video');
      return video && video.readyState >= 1;
    });
    const playerWaitMs = performance.now() - t0Player;
    const totalYMs = performance.now() - t0Y;

    results.youtube = {
      nav_ms: Number(navYMs.toFixed(2)),
      type_ms: Number(typeYMs.toFixed(2)),
      wait_results_ms: Number(waitYResultsMs.toFixed(2)),
      player_ready_ms: Number(playerWaitMs.toFixed(2)),
      total_ms: Number(totalYMs.toFixed(2)),
      first_video: firstVideoTitle,
      success: true
    };
    console.log(`  YouTube completed in ${totalYMs.toFixed(1)}ms. Video: ${firstVideoTitle}`);

    results.success = results.google_search.success && results.youtube.success;
    await browser.close();

    const outDir = path.join(PROJECT_ROOT, 'results', 'raw');
    fs.mkdirSync(outDir, { recursive: true });
    const outFile = path.join(outDir, 'puppeteer_live.json');
    fs.writeFileSync(outFile, JSON.stringify(results, null, 2), 'utf-8');

    console.log(`\n[Puppeteer Live] Saved live benchmark results to ${outFile}`);
    return results;
  } catch (err) {
    await browser.close();
    throw err;
  }
}

const args = process.argv.slice(2);
const headed = args.includes('--headed');

runLiveBenchmark({ headed }).catch(err => {
  console.error(err);
  process.exit(1);
});
