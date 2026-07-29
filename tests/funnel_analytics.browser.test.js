const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const PORT = 8791;
const BASE_URL = `http://127.0.0.1:${PORT}`;

const EVENTS = [
  {
    id: 1,
    created_at: '2026-07-04 09:00:00',
    event_name: 'attribution_ready',
    tracking_id: 'sparse-meta',
    utm_source: 'meta',
    utm_campaign: 'sparse-campaign',
    offer: 'ebook',
  },
  {
    id: 2,
    created_at: '2026-07-04 09:01:00',
    event_name: 'lp_view',
    tracking_id: 'sparse-meta',
    page_path: '/ebook',
  },
  {
    id: 3,
    created_at: '2026-07-04 09:02:00',
    event_name: 'lead_magnet_submit',
    tracking_id: 'sparse-meta',
    lead_id: 20,
  },
  {
    id: 4,
    created_at: '2026-07-04 10:00:00',
    event_name: 'lp_view',
    tracking_id: 'untrusted-label',
    page_path: '/other',
    utm_source: '<img src=x onerror="window.__funnelXss=true">',
    utm_campaign: 'unsafe-label-test',
  },
];

function startCockpit() {
  const code = [
    'import app',
    "app._current_user=lambda: 'browser-test'",
    "app.app.config['SESSION_COOKIE_SECURE']=False",
    `app.app.run(host='127.0.0.1', port=${PORT}, debug=False, threaded=True)`,
  ].join('; ');
  return spawn('python3', ['-c', code], {
    cwd: process.cwd(),
    env: { ...process.env, OPENCLAW_CRM_SESSION_SECRET: 'browser-test-only' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

async function waitForServer(processHandle) {
  let lastError;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (processHandle.exitCode != null) {
      throw new Error(`Cockpit exited before readiness with code ${processHandle.exitCode}`);
    }
    try {
      const response = await fetch(`${BASE_URL}/static/app.js?v=browser-test`);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw lastError || new Error('Cockpit readiness timeout');
}

async function run() {
  const server = startCockpit();
  let serverStderr = '';
  server.stderr.on('data', (chunk) => { serverStderr += String(chunk); });
  let browser;

  try {
    await waitForServer(server);
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 700, height: 900 } });
    const consoleErrors = [];
    const pageErrors = [];
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    page.on('pageerror', (error) => pageErrors.push(error.message));
    let funnelRequests = 0;

    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith('/api/crm/bridge/proxy/api/crm/funnel-events')) {
        funnelRequests += 1;
        if (funnelRequests > 1) {
          await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'Falha simulada de atualização' }) });
          return;
        }
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total: EVENTS.length, events: EVENTS }) });
        return;
      }
      if (url.pathname.endsWith('/api/crm/bridge/proxy/api/crm/commercial')) {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ sales: { sold_count: 2, realized_revenue: 836.4 } }) });
        return;
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    });

    await page.goto(`${BASE_URL}/#analytics`, { waitUntil: 'domcontentloaded' });
    await page.locator('.funnel-node').first().waitFor();

    assert.equal(await page.locator('#analytics-status').textContent(), '4 de 4 eventos no recorte atual.');
    assert.equal(await page.locator('#analytics-traffic-breakdown img').count(), 0, 'API-controlled labels must not create elements');
    assert.equal(await page.evaluate(() => window.__funnelXss), undefined, 'API-controlled labels must not execute script');

    await page.selectOption('#analytics-filter-source', 'meta');
    const stageCounts = await page.locator('.funnel-node strong').evaluateAll((nodes) => nodes.slice(0, 3).map((node) => node.textContent.trim()));
    assert.deepEqual(stageCounts, ['1', '1', '1'], 'source filter must preserve the matching session cohort');
    assert.equal(await page.locator('#analytics-status').textContent(), '3 de 4 eventos no recorte atual.');

    const map = page.locator('#analytics-funnel-map');
    assert.equal(await map.getAttribute('tabindex'), '0');
    assert.equal(await map.getAttribute('aria-describedby'), 'analytics-funnel-scroll-hint');
    const dimensions = await map.evaluate((element) => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth }));
    assert.ok(dimensions.scrollWidth > dimensions.clientWidth, `funnel must have internal horizontal overflow at 700px: ${JSON.stringify(dimensions)}`);

    await map.focus();
    assert.equal(await page.evaluate(() => document.activeElement && document.activeElement.id), 'analytics-funnel-map');
    const outlineStyle = await map.evaluate((element) => getComputedStyle(element).outlineStyle);
    assert.notEqual(outlineStyle, 'none', 'focused funnel must have a visible outline');
    const beforeScroll = await map.evaluate((element) => element.scrollLeft);
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(100);
    const afterScroll = await map.evaluate((element) => element.scrollLeft);
    assert.ok(afterScroll > beforeScroll, `ArrowRight must scroll the focused funnel: ${beforeScroll} -> ${afterScroll}`);

    assert.deepEqual(consoleErrors, [], 'initial rendering must not log console errors');
    assert.deepEqual(pageErrors, [], 'initial rendering must not raise page errors');

    await page.click('#analytics-refresh-btn');
    await page.locator('#analytics-status').filter({ hasText: 'Falha simulada de atualização' }).waitFor();
    assert.equal(funnelRequests, 2, 'refresh must issue a second funnel request');
    assert.deepEqual(pageErrors, [], 'handled refresh failure must not raise a page error');
    assert.ok(consoleErrors.every((message) => message.includes('500')), `only the simulated HTTP 500 may reach the console: ${JSON.stringify(consoleErrors)}`);

    console.log('FUNNEL_BROWSER_QA=PASS');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await new Promise((resolve) => {
      if (server.exitCode != null) resolve();
      else server.once('exit', resolve);
      setTimeout(resolve, 1000);
    });
    if (server.exitCode && server.exitCode !== 0 && server.exitCode !== null) {
      console.error(serverStderr);
    }
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
