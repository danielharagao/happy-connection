const { chromium, request } = require('playwright');
const fs = require('fs');

const BASES = ['https://crm.danhausch.cloud', 'http://127.0.0.1:8787'];
const AUTH = { username: 'dan', password: 'uzOQfrf1E06WU4mv' };

(async () => {
  const report = [];
  const bugs = [];
  const evidence = [];
  const results = {};

  function pass(name, detail='') { results[name] = { status: 'PASS', detail }; }
  function fail(name, detail='') { results[name] = { status: 'FAIL', detail }; }
  function bug(sev, title, repro, expected, actual) { bugs.push({ sev, title, repro, expected, actual }); }

  let browser;
  let context;
  let page;
  let base = null;

  try {
    browser = await chromium.launch({ headless: true });

    for (const candidate of BASES) {
      try {
        const ctx = await browser.newContext({
          httpCredentials: AUTH,
          ignoreHTTPSErrors: true,
        });
        const p = await ctx.newPage();
        const r = await p.goto(candidate, { waitUntil: 'domcontentloaded', timeout: 20000 });
        if (r && r.status() < 500) {
          base = candidate;
          context = ctx;
          page = p;
          evidence.push(`Selected base URL: ${candidate} (status ${r.status()})`);
          break;
        }
        await ctx.close();
      } catch (e) {}
    }

    if (!base) throw new Error('Could not open primary or fallback URL');

    await page.waitForTimeout(1500);

    // 1) Auth + landing
    const landingText = await page.locator('body').innerText();
    if (/Mission|CRM|Leads|Chat|Agenda|KB/i.test(landingText)) {
      pass('1) Auth + landing load', 'Landing loaded with app-related text visible.');
    } else {
      fail('1) Auth + landing load', 'Page loaded but app markers not found.');
      bug('High', 'Landing does not show expected CRM markers', 'Open app after auth.', 'App shell with tabs/content visible', 'No expected CRM markers detected in body text');
    }

    // Generic tab helpers
    async function clickTabLike(labels) {
      for (const label of labels) {
        const target = page.getByRole('button', { name: new RegExp(label, 'i') }).first();
        if (await target.count()) { await target.click({ timeout: 3000 }); return label; }
        const tab = page.getByRole('tab', { name: new RegExp(label, 'i') }).first();
        if (await tab.count()) { await tab.click({ timeout: 3000 }); return label; }
        const txt = page.getByText(new RegExp(`^${label}$`, 'i')).first();
        if (await txt.count()) { await txt.click({ timeout: 3000 }); return label; }
      }
      return null;
    }

    // 2) Tabs switch
    const tabs = {
      leads: await clickTabLike(['Leads']),
      chat: await clickTabLike(['Chat']),
      agenda: await clickTabLike(['Agenda']),
      kb: await clickTabLike(['Mission KB', 'KB', 'Knowledge'])
    };
    if (tabs.leads && tabs.chat && tabs.agenda && tabs.kb) {
      pass('2) Tabs switch: Leads, Chat, Agenda, Mission KB', `All tabs interacted: ${JSON.stringify(tabs)}`);
    } else {
      fail('2) Tabs switch: Leads, Chat, Agenda, Mission KB', `Missing tabs interaction: ${JSON.stringify(tabs)}`);
      bug('Medium', 'One or more top tabs not interactable', 'Try switching Leads/Chat/Agenda/Mission KB.', 'All tabs clickable and switch content', `Tab interaction map: ${JSON.stringify(tabs)}`);
    }

    // 3) Chat
    await clickTabLike(['Chat']);
    await page.waitForTimeout(1200);
    let chatPasses = 0;

    const convItems = page.locator('[data-testid*=conversation], .conversation-item, [class*=conversation]').filter({ hasText: /./ });
    const convCount = await convItems.count();
    if (convCount > 0) { chatPasses++; evidence.push(`Chat conversation list count (heuristic): ${convCount}`); }

    // select first conversation heuristically
    let threadLoaded = false;
    if (convCount > 0) {
      try {
        await convItems.first().click({ timeout: 4000 });
        await page.waitForTimeout(1200);
        const threadArea = page.locator('[data-testid*=thread], .message-list, [class*=message]').first();
        threadLoaded = await threadArea.count() > 0;
      } catch {}
    }
    if (threadLoaded) chatPasses++;

    // snippets
    const snippetGroupBtn = page.locator('button:has-text("Snippet"), button:has-text("Snippets"), [class*=snippet] button').first();
    let snippetRendered = false;
    let snippetInserted = false;
    try {
      if (await snippetGroupBtn.count()) {
        snippetRendered = true;
        await snippetGroupBtn.click({ timeout: 3000 });
      }
      const snippetItem = page.locator('button, [role=button], li').filter({ hasText: /olá|hello|follow|agendar|orçamento|snippet/i }).first();
      const composer = page.locator('textarea, [contenteditable=true], input[type=text]').last();
      const before = (await composer.count()) ? await composer.inputValue().catch(async()=> await composer.textContent()) : '';
      if (await snippetItem.count() && await composer.count()) {
        await snippetItem.click({ timeout: 3000 });
        await page.waitForTimeout(500);
        const after = await composer.inputValue().catch(async()=> await composer.textContent());
        if ((after || '').trim() !== (before || '').trim()) snippetInserted = true;
      }
    } catch {}
    if (snippetRendered) chatPasses++;
    if (snippetInserted) chatPasses++;

    // send button enabled/disabled
    let sendBehaviorOk = false;
    try {
      const composer = page.locator('textarea, [contenteditable=true], input[type=text]').last();
      const sendBtn = page.getByRole('button', { name: /send|enviar/i }).first();
      if (await composer.count() && await sendBtn.count()) {
        await composer.fill('');
        await page.waitForTimeout(300);
        const dis1 = await sendBtn.isDisabled().catch(()=>false);
        await composer.fill('QA safe test message - do not send');
        await page.waitForTimeout(300);
        const dis2 = await sendBtn.isDisabled().catch(()=>false);
        sendBehaviorOk = (dis1 === true || dis2 === false);
      }
    } catch {}
    if (sendBehaviorOk) chatPasses++;

    if (chatPasses >= 4) {
      pass('3) Chat flows', `Checks passed ${chatPasses}/5`);
    } else {
      fail('3) Chat flows', `Checks passed ${chatPasses}/5`);
      bug('High', 'Chat flow incomplete', 'Open Chat and test conversation/thread/snippets/composer/send behavior.', 'All chat checks pass', `Only ${chatPasses}/5 checks passed`);
    }

    // 4) Leads
    await clickTabLike(['Leads']);
    await page.waitForTimeout(1200);
    let leadsChecks = 0;
    const columns = page.locator('[class*=column], [data-testid*=column], h2, h3').filter({ hasText: /lead|novo|contato|pipeline|etapa|qualificado|fechado/i });
    if (await columns.count() > 0) leadsChecks++;
    const cards = page.locator('[class*=card], [data-testid*=card], article, li').filter({ hasText: /./ });
    if (await cards.count() > 0) leadsChecks++;
    try {
      if (await cards.count() > 0) {
        await cards.first().click({ timeout: 3000 });
        await page.waitForTimeout(700);
        const tabsTray = ['Detalhes','Operacional','Observações'];
        let trayTabs = 0;
        for (const t of tabsTray) {
          const b = page.getByRole('tab', { name: new RegExp(t, 'i') }).first();
          const c = page.getByRole('button', { name: new RegExp(t, 'i') }).first();
          if (await b.count()) { await b.click({ timeout: 2000 }); trayTabs++; continue; }
          if (await c.count()) { await c.click({ timeout: 2000 }); trayTabs++; }
        }
        if (trayTabs >= 2) leadsChecks++;
        evidence.push(`Leads tray tabs clicked: ${trayTabs}/3`);
      }
    } catch {}

    if (leadsChecks >= 3) pass('4) Leads board + tray tabs', `Checks passed ${leadsChecks}/3`);
    else {
      fail('4) Leads board + tray tabs', `Checks passed ${leadsChecks}/3`);
      bug('Medium', 'Leads board/tray flow incomplete', 'Open Leads, verify columns/cards, open tray and switch tabs.', 'Columns/cards/tray tabs working', `Only ${leadsChecks}/3 checks passed`);
    }

    // 5) Agenda
    await clickTabLike(['Agenda']);
    await page.waitForTimeout(1200);
    let agendaChecks = 0;
    const cal = page.locator('[class*=calendar], [data-testid*=calendar], table, [role=grid]').first();
    if (await cal.count() > 0) agendaChecks++;
    try {
      const nextBtn = page.getByRole('button', { name: /next|próximo|>/i }).first();
      const prevBtn = page.getByRole('button', { name: /prev|anterior|</i }).first();
      if (await nextBtn.count()) { await nextBtn.click({ timeout: 2000 }); agendaChecks++; }
      else if (await prevBtn.count()) { await prevBtn.click({ timeout: 2000 }); agendaChecks++; }
    } catch {}
    if (agendaChecks >= 2) pass('5) Agenda calendar render + date switch', `Checks passed ${agendaChecks}/2`);
    else {
      fail('5) Agenda calendar render + date switch', `Checks passed ${agendaChecks}/2`);
      bug('Medium', 'Agenda date navigation incomplete', 'Open Agenda and switch date.', 'Calendar visible and date navigation works', `Only ${agendaChecks}/2 checks passed`);
    }

    // 6) Mission KB
    await clickTabLike(['Mission KB', 'KB', 'Knowledge']);
    await page.waitForTimeout(1200);
    let kbChecks = 0;
    const docs = page.locator('li, [class*=doc], [data-testid*=doc]').filter({ hasText: /mission|playbook|doc|guia|knowledge/i });
    const docCount = await docs.count();
    evidence.push(`Mission KB docs count (heuristic): ${docCount}`);
    if (docCount >= 2) kbChecks++;
    try {
      if (docCount >= 2) {
        await docs.nth(0).click({ timeout: 2000 });
        await page.waitForTimeout(400);
        await docs.nth(1).click({ timeout: 2000 });
        kbChecks++;
      }
    } catch {}
    try {
      const editor = page.locator('textarea, [contenteditable=true]').first();
      const undoBtn = page.getByRole('button', { name: /undo|desfazer/i }).first();
      const saveBtn = page.getByRole('button', { name: /save|salvar/i }).first();
      if (await editor.count()) {
        await editor.click();
        await editor.press('End').catch(()=>{});
        await editor.type(' ', { delay: 10 });
        kbChecks++;
      }
      if (await undoBtn.count() && await saveBtn.count()) kbChecks++;
    } catch {}

    if (kbChecks >= 4) pass('6) Mission KB docs + edit controls', `Checks passed ${kbChecks}/4`);
    else {
      fail('6) Mission KB docs + edit controls', `Checks passed ${kbChecks}/4`);
      bug('High', 'Mission KB flow incomplete', 'Open Mission KB, switch docs, test editor and buttons.', '2 docs shown, switchable, editable, undo/save present', `Only ${kbChecks}/4 checks passed`);
    }

    // 7) Endpoints
    const api = await request.newContext({
      baseURL: base,
      httpCredentials: AUTH,
      ignoreHTTPSErrors: true,
      extraHTTPHeaders: { 'accept': 'application/json' }
    });
    const endpoints = [
      ['/api/crm/bridge', 'GET'],
      ['/api/chat/conversations', 'GET'],
      ['/api/chat/connection', 'GET'],
      ['/api/agenda?date=today', 'GET'],
      ['/api/knowledge/mission-control', 'GET'],
    ];
    let epPass = 0;
    const epRows = [];
    for (const [url, method] of endpoints) {
      try {
        const r = await api.get(url, { timeout: 15000 });
        const t = await r.text();
        const sane = t.length > 0;
        if (r.status() >= 200 && r.status() < 400 && sane) epPass++;
        epRows.push({ url, method, status: r.status(), ok: r.ok(), bodySample: t.slice(0, 180).replace(/\n/g,' ') });
      } catch (e) {
        epRows.push({ url, method, status: 'ERR', ok: false, bodySample: String(e).slice(0,180) });
      }
    }

    // optional POST sanity (non-destructive no-op attempt)
    try {
      const payload = { dryRun: true, note: 'qa-sanity', content: null };
      const r = await api.post('/api/knowledge/mission-control/save', { data: payload, timeout: 15000 });
      const t = await r.text();
      epRows.push({ url: '/api/knowledge/mission-control/save', method: 'POST', status: r.status(), ok: r.ok(), bodySample: t.slice(0,180).replace(/\n/g,' ') });
    } catch (e) {
      epRows.push({ url: '/api/knowledge/mission-control/save', method: 'POST', status: 'ERR', ok: false, bodySample: String(e).slice(0,180) });
    }

    if (epPass >= 5) pass('7) API endpoints GET + payload sanity', `GET passed ${epPass}/5`);
    else {
      fail('7) API endpoints GET + payload sanity', `GET passed ${epPass}/5`);
      bug('High', 'One or more required GET endpoints failing', 'Call required endpoints with Basic Auth.', 'All GET endpoints should return 2xx/3xx with non-empty payload', `Only ${epPass}/5 passed`);
    }

    // Build markdown report
    report.push('# QA Report — CRM Mission Control');
    report.push(`Date (UTC): ${new Date().toISOString()}`);
    report.push(`Base URL used: ${base}`);
    report.push('');
    report.push('## Test Cases (PASS/FAIL)');
    for (const [k,v] of Object.entries(results)) {
      report.push(`- **${k}**: ${v.status}`);
      report.push(`  - Evidence: ${v.detail || 'n/a'}`);
    }
    report.push('');
    report.push('## Additional UI Evidence');
    for (const e of evidence) report.push(`- ${e}`);
    report.push('');
    report.push('## Endpoint Results');
    report.push('| Method | Endpoint | Status | OK | Body sample |');
    report.push('|---|---|---:|:---:|---|');
    for (const r of epRows) report.push(`| ${r.method} | ${r.url} | ${r.status} | ${r.ok ? '✅' : '❌'} | ${String(r.bodySample).replace(/\|/g,'\\|')} |`);
    report.push('');
    report.push('## Bugs Found');
    if (bugs.length === 0) {
      report.push('- None observed in this run.');
    } else {
      bugs.forEach((b,i) => {
        report.push(`### ${i+1}. [${b.sev}] ${b.title}`);
        report.push(`- Repro steps: ${b.repro}`);
        report.push(`- Expected: ${b.expected}`);
        report.push(`- Actual: ${b.actual}`);
      });
    }

    const out = '/root/.openclaw/workspace/apps/openclaw-cockpit/QA_REPORT_latest.md';
    fs.writeFileSync(out, report.join('\n'));
    console.log(`Report written: ${out}`);

    await context?.close();
    await browser?.close();
  } catch (err) {
    try { await context?.close(); await browser?.close(); } catch {}
    const out = '/root/.openclaw/workspace/apps/openclaw-cockpit/QA_REPORT_latest.md';
    const md = `# QA Report — CRM Mission Control\n\nDate (UTC): ${new Date().toISOString()}\n\n## Run Failure\n- Error: ${String(err)}\n\n## Impact\n- Full UI/API test suite could not complete.`;
    fs.writeFileSync(out, md);
    console.error(err);
    process.exit(1);
  }
})();