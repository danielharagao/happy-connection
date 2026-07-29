const test = require('node:test');
const assert = require('node:assert/strict');
const {
  buildFunnelModel,
  filterEvents,
  formatRate,
  groupAttributedTraffic,
  groupPages,
} = require('../static/funnel-analytics.js');

const EVENTS = [
  {
    id: 1,
    created_at: '2026-07-01 10:00:00',
    event_name: 'lp_view',
    tracking_id: 't1',
    page_path: '/ebook',
    utm_source: 'meta',
    utm_campaign: 'ebook-july',
    utm_content: 'ad-video-1',
    offer: 'ebook',
  },
  {
    id: 2,
    created_at: '2026-07-01 10:01:00',
    event_name: 'attribution_ready',
    tracking_id: 't1',
    page_path: '/ebook',
    utm_source: 'meta',
    utm_campaign: 'ebook-july',
    utm_content: 'ad-video-1',
    offer: 'ebook',
  },
  {
    id: 3,
    created_at: '2026-07-01 10:02:00',
    event_name: 'lead_magnet_submit',
    tracking_id: 't1',
    lead_id: 10,
    page_path: '/ebook',
    utm_source: 'meta',
    utm_campaign: 'ebook-july',
    utm_content: 'ad-video-1',
    offer: 'ebook',
  },
  {
    id: 4,
    created_at: '2026-07-01 10:03:00',
    event_name: 'checkout_click',
    tracking_id: 't1',
    page_path: '/workshop',
    utm_source: 'meta',
    utm_campaign: 'ebook-july',
    utm_content: 'ad-video-1',
    offer: 'workshop_ia_pro',
  },
  {
    id: 5,
    created_at: '2026-07-02 11:00:00',
    event_name: 'lp_view',
    tracking_id: 't2',
    page_path: '/workshop',
    offer: 'workshop_ia_pro',
  },
  {
    id: 6,
    created_at: '2026-07-03 12:00:00',
    event_name: 'ebook_lp_view',
    tracking_id: 't3',
    page_variant: 'ebook-v2',
    utm_source: 'google',
    utm_campaign: 'agents-search',
    utm_content: 'rsa-1',
    gclid: 'g-1',
    offer: 'ebook',
  },
  {
    id: 7,
    created_at: '2026-07-03 12:02:00',
    event_name: 'ebook_form_submit',
    tracking_id: 't3',
    lead_id: 11,
    page_variant: 'ebook-v2',
    utm_source: 'google',
    utm_campaign: 'agents-search',
    utm_content: 'rsa-1',
    gclid: 'g-1',
    offer: 'ebook',
  },
];

const COMMERCIAL = { sales: { sold_count: 2, realized_revenue: 836.4 } };

test('builds coherent unique-session funnel stages and rates', () => {
  const model = buildFunnelModel(EVENTS, COMMERCIAL);

  assert.deepEqual(model.stages.map((stage) => [stage.id, stage.count]), [
    ['traffic', 3],
    ['page', 3],
    ['lead', 2],
    ['checkout', 1],
    ['purchase', 2],
  ]);
  assert.equal(model.stages[0].adAttributedCount, 2);
  assert.deepEqual(model.edges.map((edge) => edge.rate), [100, 66.7, 50, null]);
  assert.equal(model.edges.at(-1).aggregateOnly, true);
  assert.equal(model.stages.at(-1).aggregateOnly, true);
});

test('groups attributed traffic without treating direct traffic as an ad', () => {
  assert.deepEqual(groupAttributedTraffic(EVENTS), [
    { source: 'google', campaign: 'agents-search', content: 'rsa-1', count: 1 },
    { source: 'meta', campaign: 'ebook-july', content: 'ad-video-1', count: 1 },
  ]);
});

test('groups pages by path with variant fallback', () => {
  assert.deepEqual(groupPages(EVENTS), [
    { page: '/ebook', count: 1 },
    { page: '/workshop', count: 1 },
    { page: 'ebook-v2', count: 1 },
  ]);
});

test('filters by dates and attribution dimensions', () => {
  const filtered = filterEvents(EVENTS, {
    from: '2026-07-01',
    to: '2026-07-01',
    source: 'meta',
    campaign: 'ebook-july',
    offer: 'ebook',
  });
  assert.equal(filtered.length, 4);
  assert.ok(filtered.every((event) => event.tracking_id === 't1'));
});

test('attribution filters retain the complete matching session cohort', () => {
  const sparseAttribution = [
    {
      id: 20,
      created_at: '2026-07-04 09:00:00',
      event_name: 'attribution_ready',
      tracking_id: 'sparse-1',
      utm_source: 'meta',
      utm_campaign: 'sparse-campaign',
      offer: 'ebook',
    },
    {
      id: 21,
      created_at: '2026-07-04 09:01:00',
      event_name: 'lp_view',
      tracking_id: 'sparse-1',
      page_path: '/ebook',
    },
    {
      id: 22,
      created_at: '2026-07-04 09:02:00',
      event_name: 'lead_magnet_submit',
      tracking_id: 'sparse-1',
      lead_id: 20,
    },
    {
      id: 23,
      created_at: '2026-07-04 09:03:00',
      event_name: 'lp_view',
      tracking_id: 'other-session',
      page_path: '/other',
      utm_source: 'google',
    },
  ];

  const filtered = filterEvents(sparseAttribution, {
    source: 'meta',
    campaign: 'sparse-campaign',
    offer: 'ebook',
  });
  const model = buildFunnelModel(filtered, COMMERCIAL);

  assert.deepEqual(filtered.map((event) => event.id), [20, 21, 22]);
  assert.deepEqual(model.stages.slice(0, 3).map((stage) => stage.count), [1, 1, 1]);
});

test('returns null instead of a misleading percentage for a zero denominator', () => {
  assert.equal(formatRate(2, 0), null);
  assert.equal(formatRate(1, 3), 33.3);
});

test('marks checkout conversion unavailable when checkout instrumentation is absent', () => {
  const withoutCheckout = EVENTS.filter((event) => event.event_name !== 'checkout_click');
  const model = buildFunnelModel(withoutCheckout, COMMERCIAL);
  const checkoutEdge = model.edges.find((edge) => edge.to === 'checkout');
  assert.equal(checkoutEdge.rate, null);
  assert.equal(checkoutEdge.dataMissing, true);
  assert.equal(model.dataQuality.checkoutEvents, 0);
});
