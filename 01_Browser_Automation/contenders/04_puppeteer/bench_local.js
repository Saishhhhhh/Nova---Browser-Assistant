import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import puppeteer from 'puppeteer-core';
import { spawn } from 'child_process';
import http from 'http';

function ensureServerRunning(port = 8765) {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}/actions.html`, (res) => {
      resolve(null); // already running
    });
    req.on('error', () => {
      console.log(`[Puppeteer] Starting local test server on port ${port}...`);
      const serverScript = path.join(PROJECT_ROOT, 'benchmark_harness', 'server', 'app.py');
      const serverProcess = spawn('python', [serverScript, String(port)], {
        stdio: 'ignore',
        detached: true
      });
      serverProcess.unref();
      setTimeout(resolve, 800);
    });
  });
}

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

function calcStats(times) {
  if (!times || times.length === 0) return { p50: 0, p95: 0, min: 0, max: 0, mean: 0 };
  const sorted = [...times].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const p50 = sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  const p95Idx = Math.min(Math.floor(sorted.length * 0.95), sorted.length - 1);
  const p95 = sorted[p95Idx];
  const sum = sorted.reduce((acc, v) => acc + v, 0);
  const mean = sum / sorted.length;
  return {
    p50: Number(p50.toFixed(2)),
    p95: Number(p95.toFixed(2)),
    min: Number(sorted[0].toFixed(2)),
    max: Number(sorted[sorted.length - 1].toFixed(2)),
    mean: Number(mean.toFixed(2)),
  };
}

async function runBenchmark({ headed = false, iterations = 5, serverPort = 8765 } = {}) {
  await ensureServerRunning(serverPort);
  const baseUrl = `http://127.0.0.1:${serverPort}`;
  const exe = findChromeExecutable();

  console.log(`\n[Puppeteer] Launching Chrome (headed=${headed})...`);
  const t0Launch = performance.now();
  const browser = await puppeteer.launch({
    executablePath: exe,
    headless: !headed,
    defaultViewport: { width: 1280, height: 800 },
    args: ['--window-size=1280,800', '--no-default-browser-check']
  });
  const page = await browser.newPage();
  const tLaunch = performance.now() - t0Launch;
  console.log(`[Puppeteer] Browser launched in ${tLaunch.toFixed(1)} ms`);

  try {
    const navTimes = [];
    const clickTimes = [];
    const typeTimes = [];
    const scrollTimes = [];
    const domQueryTimes = [];
    const axTreeTimes = [];
    const axTreeNodeCounts = [];
    const spaFilterTimes = [];

    console.log(`\n[Puppeteer] Running ${iterations} iteration(s)...`);

    for (let it = 1; it <= iterations; it++) {
      // 1. Navigation
      const t0Nav = performance.now();
      await page.goto(`${baseUrl}/actions.html`, { waitUntil: 'load' });
      await page.waitForFunction(() => window.location.pathname.endsWith('actions.html') && window.__fixture_ready === true);
      navTimes.push(performance.now() - t0Nav);

      // 2. Click
      const t0Click = performance.now();
      await page.click('#btn-click-target');
      const clickMs = performance.now() - t0Click;
      clickTimes.push(clickMs);

      const clickText = await page.$eval('#click-status', el => el.textContent);
      if (!clickText.includes('SUCCESS')) throw new Error(`Click failed: ${clickText}`);

      // 3. Typing
      const testPhrase = 'Puppeteer benchmark keystroke latency test 12345';
      const t0Type = performance.now();
      await page.type('#input-text-target', testPhrase, { delay: 0 });
      const typeMs = performance.now() - t0Type;
      typeTimes.push(typeMs);

      const val = await page.$eval('#input-text-target', el => el.value);
      if (!val.includes(testPhrase)) throw new Error(`Typing verification failed: ${val}`);

      // 4. Scroll
      const t0Scroll = performance.now();
      await page.evaluate(() => window.scrollTo(0, 1400));
      scrollTimes.push(performance.now() - t0Scroll);

      // 5. Heavy DOM (10k nodes)
      await page.goto(`${baseUrl}/dom_heavy.html`, { waitUntil: 'load' });
      await page.waitForFunction(() => window.location.pathname.endsWith('dom_heavy.html') && window.__total_nodes === 10000);

      // Query 10k DOM needle
      const t0Query = performance.now();
      const needle = await page.$('#needle-btn');
      const box = needle ? await needle.boundingBox() : null;
      const queryMs = performance.now() - t0Query;
      domQueryTimes.push(queryMs);
      if (!box) throw new Error('Failed to query #needle-btn');

      // Accessibility Tree via CDP Session
      const t0Ax = performance.now();
      const cdp = await page.target().createCDPSession();
      const axRes = await cdp.send('Accessibility.getFullAXTree');
      const axMs = performance.now() - t0Ax;
      axTreeTimes.push(axMs);
      const nodes = axRes?.nodes || [];
      axTreeNodeCounts.push(nodes.length);
      await cdp.detach();

      // 6. Dynamic SPA Hydration & Filter
      await page.goto(`${baseUrl}/dynamic_spa.html`, { waitUntil: 'load' });
      await page.waitForFunction(() => window.location.pathname.endsWith('dynamic_spa.html') && window.__fixture_ready === true);

      // Wait for delayed hydration button
      await page.waitForSelector('#hydrated-action-btn', { visible: true, timeout: 5000 });

      // Filter products
      const t0Filter = performance.now();
      await page.type('#spa-search-input', 'Laptop', { delay: 0 });
      spaFilterTimes.push(performance.now() - t0Filter);

      console.log(`  Iteration ${it}/${iterations} done: click=${clickMs.toFixed(1)}ms, type=${typeMs.toFixed(1)}ms, 10k-query=${queryMs.toFixed(1)}ms, axTree=${axMs.toFixed(1)}ms`);
    }

    await browser.close();

    const results = {
      contender: 'puppeteer',
      environment: 'local',
      headed,
      iterations,
      cold_launch_ms: Number(tLaunch.toFixed(2)),
      navigation_ms: calcStats(navTimes),
      click_latency_ms: calcStats(clickTimes),
      type_50_chars_ms: calcStats(typeTimes),
      scroll_dispatch_ms: calcStats(scrollTimes),
      dom_10k_query_ms: calcStats(domQueryTimes),
      axtree_extraction_ms: calcStats(axTreeTimes),
      avg_axtree_nodes: Math.round(axTreeNodeCounts.reduce((a, b) => a + b, 0) / (axTreeNodeCounts.length || 1)),
      spa_filter_ms: calcStats(spaFilterTimes),
      success: true,
    };

    const outDir = path.join(PROJECT_ROOT, 'results', 'raw');
    fs.mkdirSync(outDir, { recursive: true });
    const outFile = path.join(outDir, 'puppeteer_local.json');
    fs.writeFileSync(outFile, JSON.stringify(results, null, 2), 'utf-8');

    console.log(`\n[Puppeteer] Local benchmark complete! Saved results to ${outFile}`);
    console.log('--------------------------------------------------');
    console.log(`  Cold Launch:       ${results.cold_launch_ms} ms`);
    console.log(`  Click (p50/p95):   ${results.click_latency_ms.p50} / ${results.click_latency_ms.p95} ms`);
    console.log(`  Type 50c (p50):    ${results.type_50_chars_ms.p50} ms`);
    console.log(`  10k Query (p50):   ${results.dom_10k_query_ms.p50} ms`);
    console.log(`  AXTree Dump (p50): ${results.axtree_extraction_ms.p50} ms (${results.avg_axtree_nodes} nodes)`);
    console.log('--------------------------------------------------');
    return results;
  } catch (err) {
    await browser.close();
    throw err;
  }
}

// CLI argument parsing
const args = process.argv.slice(2);
const headed = args.includes('--headed');
const smoke = args.includes('--smoke');
const itersIdx = args.indexOf('--iterations');
const iterations = smoke ? 1 : (itersIdx !== -1 ? parseInt(args[itersIdx + 1], 10) : 5);
const portIdx = args.indexOf('--port');
const serverPort = portIdx !== -1 ? parseInt(args[portIdx + 1], 10) : 8765;

runBenchmark({ headed, iterations, serverPort }).catch(err => {
  console.error(err);
  process.exit(1);
});
