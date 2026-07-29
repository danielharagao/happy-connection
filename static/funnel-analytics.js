(function initFunnelAnalytics(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.FunnelAnalytics = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function createFunnelAnalytics() {
  const VIEW_EVENTS = new Set(['lp_view', 'lead_magnet_view', 'ebook_lp_view']);
  const SUBMIT_EVENTS = new Set(['lead_magnet_submit', 'ebook_form_submit']);
  const CHECKOUT_EVENTS = new Set(['checkout_click', 'checkout_link_created', 'checkout_fallback']);

  function clean(value) {
    return String(value == null ? '' : value).trim();
  }

  function eventDate(event) {
    return clean(event && event.created_at).slice(0, 10);
  }

  function formatRate(numerator, denominator) {
    const top = Number(numerator || 0);
    const bottom = Number(denominator || 0);
    if (bottom <= 0) return null;
    return Math.round((top / bottom) * 1000) / 10;
  }

  function filterEvents(events, filters = {}) {
    const from = clean(filters.from);
    const to = clean(filters.to);
    const dimensions = [
      ['utm_source', clean(filters.source).toLowerCase()],
      ['utm_campaign', clean(filters.campaign).toLowerCase()],
      ['offer', clean(filters.offer).toLowerCase()],
    ].filter(([, value]) => Boolean(value));

    const dateFiltered = (Array.isArray(events) ? events : []).filter((event) => {
      const date = eventDate(event);
      if (from && (!date || date < from)) return false;
      if (to && (!date || date > to)) return false;
      return true;
    });

    if (!dimensions.length) return dateFiltered;

    let cohortIds = null;
    for (const [field, expected] of dimensions) {
      const matchingIds = new Set(
        dateFiltered
          .filter((event) => clean(event[field]).toLowerCase() === expected)
          .map((event) => clean(event.tracking_id))
          .filter(Boolean),
      );
      cohortIds = cohortIds == null
        ? matchingIds
        : new Set(Array.from(cohortIds).filter((trackingId) => matchingIds.has(trackingId)));
    }

    return dateFiltered.filter((event) => cohortIds.has(clean(event.tracking_id)));
  }

  function isAttributed(event) {
    return Boolean(
      clean(event && event.utm_source)
      || clean(event && event.utm_campaign)
      || clean(event && event.utm_content)
      || clean(event && event.gclid)
      || clean(event && event.fbclid)
    );
  }

  function countUniqueTracking(events) {
    return new Set((events || []).map((event) => clean(event.tracking_id)).filter(Boolean)).size;
  }

  function groupAttributedTraffic(events) {
    const groups = new Map();
    for (const event of Array.isArray(events) ? events : []) {
      const trackingId = clean(event.tracking_id);
      if (!trackingId || !isAttributed(event)) continue;
      const source = clean(event.utm_source) || (clean(event.gclid) ? 'google' : (clean(event.fbclid) ? 'meta' : 'attributed'));
      const campaign = clean(event.utm_campaign) || '(sem campanha)';
      const content = clean(event.utm_content) || '(sem criativo)';
      const key = `${source}\u0000${campaign}\u0000${content}`;
      if (!groups.has(key)) groups.set(key, { source, campaign, content, sessions: new Set() });
      groups.get(key).sessions.add(trackingId);
    }
    return Array.from(groups.values())
      .map((group) => ({ source: group.source, campaign: group.campaign, content: group.content, count: group.sessions.size }))
      .sort((a, b) => b.count - a.count
        || a.source.localeCompare(b.source)
        || a.campaign.localeCompare(b.campaign)
        || a.content.localeCompare(b.content));
  }

  function groupPages(events) {
    const groups = new Map();
    for (const event of Array.isArray(events) ? events : []) {
      if (!VIEW_EVENTS.has(clean(event.event_name))) continue;
      const trackingId = clean(event.tracking_id);
      const page = clean(event.page_path) || clean(event.page_variant) || '(página não identificada)';
      if (!trackingId) continue;
      if (!groups.has(page)) groups.set(page, new Set());
      groups.get(page).add(trackingId);
    }
    return Array.from(groups, ([page, sessions]) => ({ page, count: sessions.size }))
      .sort((a, b) => b.count - a.count || a.page.localeCompare(b.page));
  }

  function leadCount(events) {
    const trackingToLead = new Map();
    for (const event of events) {
      const trackingId = clean(event.tracking_id);
      const leadId = clean(event.lead_id);
      if (trackingId && leadId) trackingToLead.set(trackingId, leadId);
    }

    const leads = new Set();
    for (const event of events) {
      const leadId = clean(event.lead_id);
      const trackingId = clean(event.tracking_id);
      if (leadId) leads.add(`lead:${leadId}`);
      if (SUBMIT_EVENTS.has(clean(event.event_name)) && !leadId && trackingId) {
        const mappedLead = trackingToLead.get(trackingId);
        leads.add(mappedLead ? `lead:${mappedLead}` : `tracking:${trackingId}`);
      }
    }
    return leads.size;
  }

  function checkoutCount(events) {
    const checkouts = new Set();
    for (const event of events) {
      if (!CHECKOUT_EVENTS.has(clean(event.event_name))) continue;
      const trackingId = clean(event.tracking_id);
      const eventId = clean(event.id);
      if (trackingId || eventId) checkouts.add(trackingId ? `tracking:${trackingId}` : `event:${eventId}`);
    }
    return checkouts.size;
  }

  function buildFunnelModel(events, commercial = {}) {
    const safeEvents = Array.isArray(events) ? events : [];
    const traffic = countUniqueTracking(safeEvents);
    const pages = countUniqueTracking(safeEvents.filter((event) => VIEW_EVENTS.has(clean(event.event_name))));
    const leads = leadCount(safeEvents);
    const checkoutEvents = safeEvents.filter((event) => CHECKOUT_EVENTS.has(clean(event.event_name)));
    const checkout = checkoutCount(safeEvents);
    const purchases = Number(commercial && commercial.sales && commercial.sales.sold_count || 0);
    const attributed = new Set(safeEvents.filter(isAttributed).map((event) => clean(event.tracking_id)).filter(Boolean)).size;

    const stages = [
      { id: 'traffic', label: 'Tráfego rastreado', count: traffic, adAttributedCount: attributed },
      { id: 'page', label: 'Landing pages', count: pages },
      { id: 'lead', label: 'Leads', count: leads },
      { id: 'checkout', label: 'Checkout', count: checkout },
      {
        id: 'purchase',
        label: 'Compras',
        count: purchases,
        revenue: Number(commercial && commercial.sales && commercial.sales.realized_revenue || 0),
        aggregateOnly: true,
      },
    ];

    const edges = [
      { from: 'traffic', to: 'page', rate: formatRate(pages, traffic) },
      { from: 'page', to: 'lead', rate: formatRate(leads, pages) },
      {
        from: 'lead',
        to: 'checkout',
        rate: checkoutEvents.length ? formatRate(checkout, leads) : null,
        dataMissing: checkoutEvents.length === 0,
      },
      { from: 'checkout', to: 'purchase', rate: null, aggregateOnly: true },
    ];

    const linkedEvents = safeEvents.filter((event) => clean(event.lead_id)).length;
    return {
      stages,
      edges,
      traffic: groupAttributedTraffic(safeEvents),
      pages: groupPages(safeEvents),
      dataQuality: {
        events: safeEvents.length,
        linkedEvents,
        leadLinkRate: formatRate(linkedEvents, safeEvents.length),
        checkoutEvents: checkoutEvents.length,
        purchaseAttribution: 'aggregate',
      },
    };
  }

  return {
    buildFunnelModel,
    filterEvents,
    formatRate,
    groupAttributedTraffic,
    groupPages,
  };
});
