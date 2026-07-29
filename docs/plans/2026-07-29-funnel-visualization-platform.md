# Funnel Visualization Platform Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Turn the existing CRM Analytics area into a visual funnel platform that connects attributed traffic, landing pages, leads, checkout activity, and purchases while preserving the CRM as the source of truth.

**Architecture:** Extend the existing Flask Cockpit and its authenticated CRM proxy rather than introducing a separate application. Keep metric calculation in a dependency-free JavaScript module that can be tested in Node and rendered in the current frontend. In the first vertical slice, read first-party funnel events and commercial totals from the existing CRM APIs; later, add server-side aggregation and normalized Meta/Google Ads connectors for impressions, spend, CPC, CPM, and ROAS.

**Tech Stack:** Flask, vanilla JavaScript, CSS, PostgreSQL through the existing funnel backend, Python `unittest`, Node built-in test runner.

---

## Metric semantics for the first slice

| Stage | Count | Source | Limitation |
|---|---|---|---|
| Ad-attributed visits | Unique `tracking_id` values carrying `utm_*`, `gclid`, or `fbclid` | `ba_pro_funnel_events` | This is not ad impressions or platform clicks |
| Landing-page visitors | Unique `tracking_id` values with a view event | `ba_pro_funnel_events` | Anonymous visitors without a tracking ID cannot be deduplicated |
| Leads | Unique `lead_id`, falling back to submission `tracking_id` | `ba_pro_funnel_events` | Depends on retroactive lead linking |
| Checkout visitors | Unique `tracking_id`, falling back to event ID, with checkout activity | `ba_pro_funnel_events` | Checkout-link creation is intent, not purchase |
| Purchases | `commercial.sales.sold_count` | Existing CRM commercial endpoint / Asaas reconciliation | Aggregate only; shown as a separate outcome card until purchases are linked to tracking IDs |

Every cohort-compatible edge rate is `downstream / upstream`. The UI must display `N/D` when the denominator is zero. The checkout → purchase connector must remain dashed and show `Atribuição pendente`, never a percentage, while purchases are aggregate-only.

## Task 1: Protect the CRM proxy contract

**Objective:** Allow only the two read-only analytics endpoints required by the visualization.

**Files:**
- Modify: `app.py:179`
- Modify: `tests/test_crm_bridge_api_unittest.py`

**Step 1: Write failing tests**

Add tests that assert:

```python
self.assertTrue(cockpit_app._crm_proxy_path_allowed("api/crm/funnel-events"))
self.assertTrue(cockpit_app._crm_proxy_path_allowed("api/crm/commercial"))
self.assertFalse(cockpit_app._crm_proxy_path_allowed("api/crm/private"))
```

**Step 2: Verify RED**

Run:

```bash
python3 -m unittest tests.test_crm_bridge_api_unittest.CrmBridgeApiTests.test_analytics_proxy_paths_are_allowlisted -v
```

Expected: FAIL because the committed baseline allows only overview and lead paths.

**Step 3: Implement minimally**

Extend `CRM_ALLOWED_PROXY_PREFIXES` with the exact read-only paths:

```python
"api/crm/funnel-events",
"api/crm/commercial",
```

Do not allow a broad `api/crm/` prefix.

**Step 4: Verify GREEN**

Run the targeted test, then the full Python suite.

**Step 5: Commit**

```bash
git add app.py tests/test_crm_bridge_api_unittest.py
git commit -m "feat: allow funnel analytics CRM endpoints"
```

## Task 2: Build the tested funnel calculation module

**Objective:** Produce deterministic funnel nodes, edges, rates, ad groups, and page groups from CRM payloads.

**Files:**
- Create: `static/funnel-analytics.js`
- Create: `tests/funnel_analytics.test.js`

**Step 1: Write one failing Node test**

Use a fixture containing duplicate events in one tracking session, one linked lead, one checkout, and two purchases. Assert unique stage counts and edge rates.

**Step 2: Verify RED**

Run:

```bash
node --test tests/funnel_analytics.test.js
```

Expected: FAIL because the module does not exist.

**Step 3: Implement minimally**

Export:

```javascript
buildFunnelModel(events, commercial)
filterEvents(events, filters)
groupAttributedTraffic(events)
groupPages(events)
formatRate(numerator, denominator)
```

Use a small UMD wrapper so the same file works in Node and the browser without a bundler.

**Step 4: Add vertical tests one at a time**

Cover:

- session deduplication;
- zero denominator returns `null` / `N/D`;
- direct traffic is not counted as ad-attributed;
- `utm_source`, `utm_campaign`, and `utm_content` grouping;
- `page_path` fallback to `page_variant`;
- purchase count is marked `aggregateOnly: true` and the checkout → purchase rate remains `null`;
- date, source, campaign, and offer filters.

Run each new test RED then GREEN.

**Step 5: Commit**

```bash
git add static/funnel-analytics.js tests/funnel_analytics.test.js
git commit -m "feat: calculate visual funnel metrics"
```

## Task 3: Add the Analytics navigation and accessible graph shell

**Objective:** Add a visual Analytics tab to the committed CRM baseline.

**Files:**
- Modify: `templates/index.html`
- Modify: `tests/test_crm_ui_markers_unittest.py`

**Step 1: Write failing marker tests**

Assert the presence of:

- `data-target="analytics"`;
- `id="panel-analytics"`;
- date/source/campaign/offer filters;
- `id="analytics-funnel-map"`;
- `id="analytics-traffic-breakdown"`;
- `id="analytics-pages-breakdown"`;
- a visible first-party-data limitation note;
- `<script src="/static/funnel-analytics.js"></script>` before `app.js`.

**Step 2: Verify RED**

Run the targeted Python test and confirm the markers are absent.

**Step 3: Implement minimally**

Add the tab and panel using Portuguese UI copy consistent with the existing CRM. Keep tables and controls keyboard-accessible.

**Step 4: Verify GREEN**

Run the marker test and full Python suite.

**Step 5: Commit**

```bash
git add templates/index.html tests/test_crm_ui_markers_unittest.py
git commit -m "feat: add funnel visualization workspace"
```

## Task 4: Render the funnel graph and filters

**Objective:** Load current CRM data and render connected stages with conversion rates.

**Files:**
- Modify: `static/app.js`
- Modify: `static/styles.css`
- Modify: `tests/test_crm_ui_markers_unittest.py`

**Step 1: Write failing integration-marker tests**

Assert that `app.js`:

- loads both `/api/crm/bridge/proxy/api/crm/funnel-events?limit=500` and `/api/crm/bridge/proxy/api/crm/commercial`;
- calls `FunnelAnalytics.buildFunnelModel`;
- loads Analytics when its tab activates;
- binds refresh and filter controls.

Assert CSS contains responsive funnel-node, connector, bottleneck, and data-quality styles.

**Step 2: Verify RED**

Run the targeted test and confirm failure.

**Step 3: Implement minimally**

Add:

```javascript
loadFunnelAnalytics()
renderFunnelMap(model)
renderTrafficBreakdown(rows)
renderPagesBreakdown(rows)
applyAnalyticsFilters()
```

Use `Promise.all` for the two independent API reads. Render stage cards and connectors with semantic HTML/CSS rather than introducing a chart dependency.

**Step 4: Verify GREEN**

Run targeted and full suites, plus:

```bash
node --check static/app.js
node --check static/funnel-analytics.js
```

**Step 5: Commit**

```bash
git add static/app.js static/styles.css tests/test_crm_ui_markers_unittest.py
git commit -m "feat: render CRM funnel conversion graph"
```

## Task 5: Exercise the first slice locally

**Objective:** Prove the UI works as an integrated artifact without touching production.

**Files:**
- Create: `tests/fixtures/funnel-analytics.json`
- Create: `tests/test_funnel_visualization_browser.py` or an equivalent existing browser-test fixture

**Steps:**

1. Add a deterministic fixture with ads, pages, leads, checkout, and aggregate sales.
2. Start the Flask app in the isolated worktree with a test CRM upstream or route interception.
3. Open `/#analytics` in a browser.
4. Verify stage values, rates, filters, responsive layout, keyboard labels, and empty-state behavior.
5. Capture a screenshot under `artifacts/funnel-visualization/`.
6. Run all Python and Node tests.
7. Commit with `test: verify funnel visualization end to end`.

## Task 6: Add server-side analytics aggregation

**Objective:** Move bounded aggregation and date filtering into the funnel backend before event volume exceeds the 500-row client limit.

**Files:**
- Modify: `/root/.openclaw/workspace/funnel_backend.py`
- Modify: `/root/.openclaw/workspace/tests/test_funnel_crm_unittest.py`

**Contract:**

```http
GET /api/crm/funnel-analytics?from=YYYY-MM-DD&to=YYYY-MM-DD&source=&campaign=&offer=
```

Return `stages`, `edges`, `traffic`, `pages`, `data_quality`, and `generated_at`. Use parameterized SQL and validated date ranges. Include `page_path` in the event data contract. Add indexes only after `EXPLAIN ANALYZE` demonstrates need.

Deploy only after backup, dry-run query verification, service restart, local authenticated probe, and rollback validation.

## Task 7: Normalize ad-platform entities and connectors

**Objective:** Add real ad spend, impressions, clicks, and creative-level performance.

**Data model:**

- `marketing_ad_accounts`
- `marketing_campaigns`
- `marketing_ad_sets`
- `marketing_ads`
- `marketing_ad_daily_metrics`
- `marketing_page_registry`
- `marketing_funnel_definitions`
- `marketing_funnel_nodes`
- `marketing_funnel_edges`

Use provider-native IDs as immutable external keys. Store daily snapshots by account/campaign/ad set/ad/date. Never infer platform impressions from landing-page events.

**Connector order:**

1. Meta Ads read-only connector;
2. Google Ads read-only connector;
3. scheduled incremental sync with idempotent upsert;
4. source-health UI and stale-data warnings;
5. CPC, CPM, CTR, CPL, CAC, revenue, and ROAS calculations.

Credentials remain outside Git and all connector scopes must be read-only.

## Task 8: Production rollout

1. Review the feature branch diff against the dirty live CRM tree.
2. Rebase or cherry-pick into a clean deployment branch; never overwrite unrelated live changes.
3. Back up `app.py`, `templates/index.html`, `static/app.js`, and `static/styles.css`.
4. Run all tests and syntax checks.
5. Deploy atomically.
6. Restart the Cockpit service only if `app.py` changed.
7. Verify authenticated Analytics UI and CRM proxy responses.
8. Confirm no CRM write endpoints or messaging actions were triggered.
9. Keep rollback files and evidence paths in the deployment report.

## Acceptance criteria

- [ ] A user can open Analytics inside the current CRM.
- [ ] The screen visibly connects attributed traffic → pages → leads → checkout → purchases.
- [ ] Each cohort-compatible connector shows count and conversion rate.
- [ ] Aggregate-only purchase data uses a dashed connector with no fabricated conversion rate.
- [ ] Filters update the graph without a page reload.
- [ ] Direct traffic is separated from ad-attributed traffic.
- [ ] Aggregate-only purchase attribution is disclosed.
- [ ] Empty and zero-denominator states never show misleading `0%`.
- [ ] Existing CRM navigation, lead management, and authentication tests remain green.
- [ ] No ad-platform metric is fabricated from first-party web events.
