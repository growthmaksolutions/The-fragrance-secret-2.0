/* ═══════════════════════════════════════════════════════════════════════
   GA4 CHECKOUT EVENTS — Shopify custom pixel

   NOT loaded by the theme. This file is the source of truth for code that
   has to be pasted into:

     Shopify admin › Settings › Customer events › Add custom pixel

   Name it "GA4 checkout", paste everything below the banner, set Permission
   to "Analytics", and Save, then Connect.

   ── Why it cannot live in the theme ──────────────────────────────────────

   Checkout is not themeable. layout/theme.liquid never renders on the
   checkout or thank-you pages, so assets/analytics.js stops at
   begin_checkout — it fires when the shopper leaves for checkout and then
   goes blind. Everything after that (shipping, payment, the order itself)
   is only visible to a pixel in the sandbox Shopify provides.

   Without this pixel there is no purchase event, which means no conversion
   rate, no revenue per session, and no checkout completion rate — three of
   the KPIs the funnel work was done for. The theme-side tracking is half a
   funnel on its own.

   ── Replace before pasting ───────────────────────────────────────────────

   GA4_MEASUREMENT_ID below must be the same G- id set in
   Theme settings › Analytics, or the checkout events land in a different
   property from the browsing events and the funnel will not join up.

   ── On deduplication ─────────────────────────────────────────────────────

   purchase is sent with the Shopify order id as transaction_id. GA4
   deduplicates on that key, so a shopper who refreshes the thank-you page,
   or returns to it from the confirmation email, does not book the revenue
   twice. This is the P0 the guide asks for; it is handled by the id, not by
   trying to fire the event only once.

   The pixel runs in a sandboxed worker with no access to the page DOM — it
   cannot read window.dataLayer from the storefront, which is why it talks to
   GA4 over the Measurement Protocol-style gtag endpoint it loads itself.
   ═══════════════════════════════════════════════════════════════════════ */

/* ─────────────── paste from here ─────────────── */

const GA4_MEASUREMENT_ID = 'G-XXXXXXXXXX'; // ← replace

/* The sandbox has no <script> of its own to hang gtag on, so load the
   library and keep the usual shim. */
const script = document.createElement('script');
script.async = true;
script.src = 'https://www.googletagmanager.com/gtag/js?id=' + GA4_MEASUREMENT_ID;
document.head.appendChild(script);

window.dataLayer = window.dataLayer || [];
function gtag() { window.dataLayer.push(arguments); }
gtag('js', new Date());
gtag('config', GA4_MEASUREMENT_ID, { send_page_view: false });

/* Shopify money objects are { amount, currencyCode } with amount already in
   major units — unlike /cart.js, which is in cents. Do not divide by 100. */
function money(m) {
  return m && typeof m.amount === 'number' ? m.amount : 0;
}

function itemsFrom(lines) {
  return (lines || []).map(function (line, i) {
    const v = line.variant || {};
    const p = v.product || {};
    const item = {
      item_id: String(p.id || v.id || ''),
      item_name: p.title || v.title || '',
      price: money(v.price),
      quantity: line.quantity,
      index: i
    };
    if (p.vendor) item.item_brand = p.vendor;
    if (p.type) item.item_category = p.type;
    if (v.title && v.title !== 'Default Title') item.item_variant = v.title;
    return item;
  });
}

analytics.subscribe('checkout_started', (event) => {
  const c = event.data.checkout;
  gtag('event', 'begin_checkout', {
    currency: c.currencyCode,
    value: money(c.totalPrice),
    items: itemsFrom(c.lineItems)
  });
});

analytics.subscribe('checkout_contact_info_submitted', (event) => {
  const c = event.data.checkout;
  /* Not a GA4 recommended event. It is here because the gap between
     begin_checkout and add_shipping_info is where "forced account creation"
     and "too long / complicated" abandonment shows up, and without a step
     between them that drop is invisible. */
  gtag('event', 'checkout_contact_submitted', {
    currency: c.currencyCode,
    value: money(c.totalPrice)
  });
});

analytics.subscribe('checkout_shipping_info_submitted', (event) => {
  const c = event.data.checkout;
  gtag('event', 'add_shipping_info', {
    currency: c.currencyCode,
    value: money(c.totalPrice),
    shipping_tier: (c.delivery && c.delivery.selectedDeliveryOptions &&
                    c.delivery.selectedDeliveryOptions[0] &&
                    c.delivery.selectedDeliveryOptions[0].title) || undefined,
    items: itemsFrom(c.lineItems)
  });
});

analytics.subscribe('payment_info_submitted', (event) => {
  const c = event.data.checkout;
  gtag('event', 'add_payment_info', {
    currency: c.currencyCode,
    value: money(c.totalPrice),
    /* COD versus prepaid is the split that matters most for this store —
       delivered revenue, not placed revenue, is the number worth optimising
       in a COD market, and that cannot be segmented without this. */
    payment_type: (c.transactions && c.transactions[0] && c.transactions[0].gateway) || undefined,
    items: itemsFrom(c.lineItems)
  });
});

analytics.subscribe('checkout_completed', (event) => {
  const c = event.data.checkout;
  gtag('event', 'purchase', {
    /* GA4 deduplicates on this. See the note in the banner above. */
    transaction_id: String(c.order && c.order.id ? c.order.id : c.token),
    currency: c.currencyCode,
    value: money(c.totalPrice),
    tax: money(c.totalTax),
    shipping: money(c.shippingLine && c.shippingLine.price),
    coupon: (c.discountApplications && c.discountApplications[0] &&
             c.discountApplications[0].title) || undefined,
    items: itemsFrom(c.lineItems)
  });
});

/* Payment failures never reach a thank-you page, so they are invisible in
   every funnel report unless they are reported here. 10% of abandoning
   shoppers in the Baymard data leave on a declined card; this is how that
   10% becomes something you can see and build a retry flow for. */
analytics.subscribe('alert_displayed', (event) => {
  const d = event.data || {};
  gtag('event', 'checkout_error', {
    error_message: d.alert && d.alert.message ? d.alert.message : 'unknown',
    error_type: d.alert && d.alert.type ? d.alert.type : undefined
  });
});
