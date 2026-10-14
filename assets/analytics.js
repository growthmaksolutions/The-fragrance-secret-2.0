/* ═══════════════════════════════════════════════════════════════════════
   GA4 ECOMMERCE EVENT STREAM

   Fires the recommended GA4 ecommerce events into window.dataLayer, which
   analytics-init.liquid has already opened and seeded with the page context.
   A GTM container reads them from there; with a bare measurement ID gtag
   reads the same pushes.

   The design decision worth knowing about is how adds and removes are
   detected. This theme has five ways to change the cart — the product form,
   Quick Add on a card, the concierge, the drawer's quantity steppers, the
   cart page's own rows — and instrumenting each call site means every new
   one silently goes untracked. Instead every path already ends in the same
   place: a `cart:updated` event carrying the whole cart. So this file holds
   the previous cart and diffs against it. One hook, and anything that moves
   the cart is covered, including code not yet written.

   Nothing here throws into the page. An analytics file that can break Add to
   Cart is worse than no analytics at all, so every handler is wrapped and
   failures are swallowed (surfaced in the console only with the debug
   setting on).
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var CFG = window.TFSAnalytics;
  if (!CFG) return;

  var dl = (window.dataLayer = window.dataLayer || []);
  var DEBUG = !!CFG.debug;

  function log() {
    if (!DEBUG || !window.console) return;
    try { console.log.apply(console, ['[TFS analytics]'].concat([].slice.call(arguments))); } catch (e) { /* no-op */ }
  }

  /* Every handler goes through this. See the header: analytics must never be
     the reason a shopper cannot buy something. */
  function safe(fn) {
    return function () {
      try { return fn.apply(this, arguments); }
      catch (e) { log('handler failed', e); }
    };
  }

  /* GA4 wants ecommerce cleared between pushes or the previous event's items
     leak into the next one — a documented GTM gotcha, not a superstition. */
  function push(name, ecommerce) {
    dl.push({ ecommerce: null });
    var payload = { event: name, ecommerce: ecommerce };
    dl.push(payload);
    log(name, ecommerce);
  }

  function money(cents) {
    return Math.round((Number(cents) || 0)) / 100;
  }

  /* ── Item builders ──────────────────────────────────────────────────── */

  /* A Shopify /cart.js line → a GA4 item. final_price is the per-unit price
     after line discounts, which is what was actually charged; original_price
     would overstate revenue on anything in a promotion. */
  function itemFromCartLine(line, index) {
    var item = {
      item_id: String(line.product_id),
      item_name: line.product_title || line.title,
      item_brand: line.vendor || undefined,
      item_category: line.product_type || undefined,
      price: money(line.final_price),
      quantity: line.quantity
    };
    if (line.variant_title && line.variant_title !== 'Default Title') item.item_variant = line.variant_title;
    if (typeof index === 'number') item.index = index;
    return item;
  }

  /* A product card → a GA4 item. The attributes are written by
     snippets/product-card.liquid; a card without them still yields an item
     with an id and a name, which is enough to attribute the click. */
  function itemFromCard(card, index) {
    if (!card) return null;
    var id = card.getAttribute('data-pid');
    if (!id) return null;
    var item = {
      item_id: String(id),
      item_name: card.getAttribute('data-ga-name') || '',
      index: typeof index === 'number' ? index : undefined
    };
    var brand = card.getAttribute('data-ga-brand');
    var cat = card.getAttribute('data-ga-cat');
    var price = card.getAttribute('data-ga-price');
    if (brand) item.item_brand = brand;
    if (cat) item.item_category = cat;
    if (price) item.price = Number(price);
    if (CFG.list) {
      item.item_list_id = CFG.list.id || undefined;
      item.item_list_name = CFG.list.name || undefined;
    }
    return item;
  }

  function cartTotal(cart) {
    return money(cart && cart.total_price);
  }

  /* ── Consent ────────────────────────────────────────────────────────── */

  /* analytics-init.liquid sets Consent Mode to denied across the board. This
     lifts it when Shopify's Customer Privacy API says the shopper has agreed
     — the API a consent banner app writes to. On a store with no banner the
     API reports consent as allowed by default, so this is not a switch that
     silently turns tracking off; it is the one that keeps a banner's answer
     honest.

     A storefront without the API loaded at all leaves the defaults alone. */
  function syncConsent() {
    var api = window.Shopify && window.Shopify.customerPrivacy;
    if (!api || typeof window.gtag !== 'function') return;
    try {
      var analyticsOk = api.analyticsProcessingAllowed && api.analyticsProcessingAllowed();
      var marketingOk = api.marketingAllowed && api.marketingAllowed();
      window.gtag('consent', 'update', {
        analytics_storage: analyticsOk ? 'granted' : 'denied',
        ad_storage: marketingOk ? 'granted' : 'denied',
        ad_user_data: marketingOk ? 'granted' : 'denied',
        ad_personalization: marketingOk ? 'granted' : 'denied'
      });
      log('consent', { analytics: analyticsOk, marketing: marketingOk });
    } catch (e) { log('consent read failed', e); }
  }

  document.addEventListener('visitorConsentCollected', safe(syncConsent));
  /* The API loads asynchronously and may not be there on first run. */
  if (window.Shopify && window.Shopify.loadFeatures) {
    try {
      window.Shopify.loadFeatures([{ name: 'consent-tracking-api', version: '0.1' }], safe(syncConsent));
    } catch (e) { syncConsent(); }
  } else {
    syncConsent();
  }

  /* ── view_item ──────────────────────────────────────────────────────── */

  if (CFG.pageType === 'product' && CFG.item) {
    push('view_item', {
      currency: CFG.currency,
      value: CFG.item.price,
      items: [CFG.item]
    });
  }

  /* ── search ─────────────────────────────────────────────────────────── */

  /* Fired with the result count, because the zero-result rate is a KPI in its
     own right and GA4 cannot derive it from the term alone. */
  if (CFG.search) {
    dl.push({
      event: 'search',
      search_term: CFG.search.term,
      search_results: CFG.search.results
    });
    log('search', CFG.search);
    if (CFG.search.results === 0) {
      dl.push({ event: 'search_zero_results', search_term: CFG.search.term });
      log('search_zero_results', CFG.search.term);
    }
  }

  /* ── view_item_list ─────────────────────────────────────────────────── */

  /* Fired per grid, once, when the grid first comes into view — not on page
     load. A list the shopper never scrolled to was not viewed, and counting
     it inflates the denominator of every list-level click-through rate.

     Grids are also rendered client-side on some templates, so the observer is
     attached as grids appear rather than only at init. */
  var seenLists = typeof WeakSet !== 'undefined' ? new WeakSet() : null;
  var listSeen = [];

  function alreadySeen(grid) {
    if (seenLists) return seenLists.has(grid);
    return listSeen.indexOf(grid) !== -1;
  }
  function markSeen(grid) {
    if (seenLists) seenLists.add(grid);
    else listSeen.push(grid);
  }

  function reportList(grid) {
    if (alreadySeen(grid)) return;
    var cards = [].slice.call(grid.querySelectorAll('.prod-card'));
    if (!cards.length) return;
    markSeen(grid);
    var items = [];
    cards.forEach(function (card, i) {
      var item = itemFromCard(card, i);
      if (item) items.push(item);
    });
    if (!items.length) return;
    push('view_item_list', {
      item_list_id: (CFG.list && CFG.list.id) || undefined,
      item_list_name: (CFG.list && CFG.list.name) || undefined,
      items: items
    });
  }

  var gridObserver = null;
  if (window.IntersectionObserver) {
    gridObserver = new IntersectionObserver(safe(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        gridObserver.unobserve(entry.target);
        reportList(entry.target);
      });
    }), { rootMargin: '0px 0px -20% 0px', threshold: 0.01 });
  }

  function watchGrids() {
    var grids = document.querySelectorAll('.products-grid, .hub-grid');
    [].forEach.call(grids, function (grid) {
      if (grid.hasAttribute('data-ga-watched')) return;
      grid.setAttribute('data-ga-watched', '');
      if (gridObserver) gridObserver.observe(grid);
      else reportList(grid);
    });
  }

  /* ── select_item ────────────────────────────────────────────────────── */

  document.addEventListener('click', safe(function (e) {
    var card = e.target.closest && e.target.closest('.prod-card');
    if (!card) return;
    /* Quick Add and the wishlist heart are their own events, fired elsewhere.
       Counting them as a list click would double-count the interaction. */
    if (e.target.closest('.quick-add') || e.target.closest('.pa-wish')) return;
    var item = itemFromCard(card);
    if (!item) return;
    push('select_item', {
      item_list_id: (CFG.list && CFG.list.id) || undefined,
      item_list_name: (CFG.list && CFG.list.name) || undefined,
      items: [item]
    });
  }), true);

  /* ── add_to_cart / remove_from_cart, by cart diff ───────────────────── */

  /* Keyed by line key, which is variant id + a hash of the line properties —
     so a Custom Mixed Spray blended from two different oils is two lines, and
     a quantity change on one is not read as a change on the other. */
  function indexCart(cart) {
    var map = {};
    if (!cart || !cart.items) return map;
    cart.items.forEach(function (line, i) { map[line.key] = { line: line, index: i }; });
    return map;
  }

  var prevIndex = null;

  function diffCart(cart) {
    var next = indexCart(cart);
    /* First sight of the cart: record it, report nothing. A page load is not
       an add, and firing one here would credit every refresh with the whole
       basket. */
    if (prevIndex === null) { prevIndex = next; return; }

    var added = [], removed = [], key;

    for (key in next) {
      if (!Object.prototype.hasOwnProperty.call(next, key)) continue;
      var nowQty = next[key].line.quantity;
      var wasQty = prevIndex[key] ? prevIndex[key].line.quantity : 0;
      if (nowQty > wasQty) {
        var addItem = itemFromCartLine(next[key].line, next[key].index);
        addItem.quantity = nowQty - wasQty;
        added.push(addItem);
      } else if (nowQty < wasQty) {
        var cutItem = itemFromCartLine(next[key].line, next[key].index);
        cutItem.quantity = wasQty - nowQty;
        removed.push(cutItem);
      }
    }
    /* Lines gone from the cart entirely — a remove, or a quantity taken to 0. */
    for (key in prevIndex) {
      if (!Object.prototype.hasOwnProperty.call(prevIndex, key)) continue;
      if (next[key]) continue;
      removed.push(itemFromCartLine(prevIndex[key].line, prevIndex[key].index));
    }

    prevIndex = next;

    if (added.length) {
      push('add_to_cart', {
        currency: CFG.currency,
        value: added.reduce(function (sum, i) { return sum + i.price * i.quantity; }, 0),
        items: added
      });
    }
    if (removed.length) {
      push('remove_from_cart', {
        currency: CFG.currency,
        value: removed.reduce(function (sum, i) { return sum + i.price * i.quantity; }, 0),
        items: removed
      });
    }
  }

  document.addEventListener('cart:updated', safe(function (e) {
    if (e && e.detail) diffCart(e.detail);
  }));

  /* Seed the baseline so the first real change diffs against the truth rather
     than against nothing. Cheap, cached, and it also catches a cart filled in
     another tab. */
  function seedCart() {
    fetch('/cart.js', { headers: { Accept: 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(safe(function (cart) {
        if (prevIndex === null) prevIndex = indexCart(cart);
        lastCart = cart;
      }))
      .catch(function () { /* offline or blocked: diffing starts at first change */ });
  }

  /* ── view_cart ──────────────────────────────────────────────────────── */

  var lastCart = null;
  document.addEventListener('cart:updated', safe(function (e) {
    if (e && e.detail) lastCart = e.detail;
  }));

  function viewCart(cart) {
    if (!cart || !cart.items || !cart.items.length) return;
    push('view_cart', {
      currency: CFG.currency,
      value: cartTotal(cart),
      items: cart.items.map(itemFromCartLine)
    });
  }

  if (CFG.pageType === 'cart') {
    fetch('/cart.js', { headers: { Accept: 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(safe(function (cart) { lastCart = cart; if (prevIndex === null) prevIndex = indexCart(cart); viewCart(cart); }))
      .catch(function () { /* no-op */ });
  } else {
    seedCart();
  }

  /* The drawer opening is the mini-cart view the guide counts. app.js owns
     openCart and exposes it on window, so it is wrapped rather than
     re-implemented — the drawer keeps one opener and this stays a decorator.

     Guarded against repeat fires: opening the drawer three times while adding
     three items is one cart view, not three. Reset whenever the cart changes
     so a later open after a real change counts again. */
  var cartViewed = false;
  document.addEventListener('cart:updated', function () { cartViewed = false; });

  function wrapOpenCart() {
    if (typeof window.openCart !== 'function' || window.openCart.__gaWrapped) return false;
    var inner = window.openCart;
    var wrapped = function () {
      var r = inner.apply(this, arguments);
      if (!cartViewed) {
        cartViewed = true;
        /* The drawer refreshes its contents around the open, so read the cart
           rather than trusting a snapshot taken before the add landed. */
        fetch('/cart.js', { headers: { Accept: 'application/json' } })
          .then(function (res) { return res.json(); })
          .then(safe(function (cart) { lastCart = cart; viewCart(cart); }))
          .catch(function () { viewCart(lastCart); });
      }
      return r;
    };
    wrapped.__gaWrapped = true;
    window.openCart = wrapped;
    return true;
  }

  /* ── begin_checkout ─────────────────────────────────────────────────── */

  /* Both routes out of the cart: the theme's own Checkout button, and
     Shopify's dynamic payment buttons, which skip the cart page entirely. */
  document.addEventListener('click', safe(function (e) {
    var t = e.target;
    if (!t.closest) return;
    var trigger = t.closest('[name="checkout"], .cd-checkout, .shopify-payment-button__button');
    if (!trigger) return;
    var cart = lastCart;
    if (!cart || !cart.items || !cart.items.length) return;
    push('begin_checkout', {
      currency: CFG.currency,
      value: cartTotal(cart),
      items: cart.items.map(itemFromCartLine)
    });
  }), true);

  /* ── add_to_wishlist ────────────────────────────────────────────────── */

  document.addEventListener('click', safe(function (e) {
    var btn = e.target.closest && e.target.closest('[data-wish]');
    if (!btn) return;
    /* aria-pressed is the state BEFORE the toggle handler runs, so "false"
       here means this click is the save. Removals are not an ecommerce event
       in GA4 and are left out rather than reported as a save. */
    if (btn.getAttribute('aria-pressed') === 'true') return;
    var card = btn.closest('.prod-card');
    var item = card ? itemFromCard(card) : (CFG.item || null);
    if (!item) return;
    push('add_to_wishlist', {
      currency: CFG.currency,
      value: item.price || 0,
      items: [item]
    });
  }), true);

  /* ── Form errors ────────────────────────────────────────────────────── */

  /* A custom event, not a GA4 recommended one. The guide asks for form errors
     to be tracked because they are invisible in a funnel: the shopper simply
     stops, and nothing records why. */
  window.TFSTrackFormError = safe(function (formName, field, message) {
    dl.push({ event: 'form_error', form_name: formName, form_field: field, error_message: message });
    log('form_error', formName, field, message);
  });

  /* ── Init ───────────────────────────────────────────────────────────── */

  function init() {
    watchGrids();
    if (!wrapOpenCart()) {
      /* app.js defines openCart at parse time, but a deferred or re-ordered
         load should not cost the event. Retry briefly, then give up. */
      var tries = 0;
      var timer = setInterval(function () {
        if (wrapOpenCart() || ++tries > 20) clearInterval(timer);
      }, 250);
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', safe(init));
  else init();

  /* Grids that arrive later — client-rendered recommendations, Load More. */
  if (window.MutationObserver) {
    var mo = new MutationObserver(safe(function () { watchGrids(); }));
    if (document.body) mo.observe(document.body, { childList: true, subtree: true });
    else document.addEventListener('DOMContentLoaded', function () {
      mo.observe(document.body, { childList: true, subtree: true });
    });
  }
})();
