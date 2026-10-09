# Judge.me review requests — setup

Two jobs, in this order. The first puts reviews on product pages this month;
the second keeps them arriving.

Neither is code. Both are configuration in the Judge.me admin, which is why
neither is blocked on the theme being up to date.

---

## 1 — Ask the customers you already have

The store has **1,453 non-cancelled orders** going back to March 2025, and
review requests have never gone out for them. That is the single largest
source of real reviews available, and it costs nothing.

**Judge.me › Settings › Request reviews › "Request reviews from previous
Shopify orders" › Get started.**

| Field | Set it to | Why |
|---|---|---|
| Start date | A date before Judge.me was installed | It pulls fulfilled orders between that date and today |
| Maximum emails per order | **1** | Judge.me's own recommendation; more than one reads as pressure |

Worth knowing before running it:

- It processes **up to 5,000 orders**, then stops. 1,453 is comfortably inside that.
- Cancelled, refunded and returned orders are **skipped automatically**.
- It is built as a **one-time import**. Running it again over the same dates
  reports "0 orders processed" — duplicate detection, not a failure.
- Because it is one-shot, get the date right first. Start with the earliest
  date you are comfortable emailing, not an arbitrary recent one.

One judgement call that is yours, not Judge.me's: emailing someone who
bought eighteen months ago is a cold email. If that sits badly, set the start
date to six months back instead and accept fewer reviews.

---

## 2 — Keep them arriving

**Judge.me › Settings › Request scheduling › Request Timing**, then pick the
order type (Domestic orders for the UAE).

Set **"After the order is fulfilled, send the review request after"** to a
number of days between 0 and 60. The default is 14.

**Suggested: 5–7 days for domestic orders.** The reasoning is specific to what
is being sold. UAE delivery is 1–4 working days, so at 5–7 days the bottle has
arrived and been worn two or three times — long enough to have an opinion
about longevity and sillage, which is what fragrance reviews are actually
useful for, and early enough that the purchase is still recent. Fourteen days
is a long time to remember a scent you tried once.

Note the timing fires off **fulfilment**, not order placement, and changes
apply to orders fulfilled after you save. Requests already queued are not
rewritten.

---

## What to check a week later

- Reviews arriving and published.
- `reviews.rating_count` appearing on products in Shopify. Judge.me writes it,
  and the PDP rating row reads it — the row renders nothing without it.
- The rating row itself live on the PDP, which needs commit `6eecd0e`
  deployed. Reviews alone will not make it appear.

Source: [automatic review request emails](https://judge.me/help/en/articles/8379844-automatic-review-request-emails) ·
[past Shopify orders](https://judge.me/help/en/articles/8380029-adding-review-requests-for-past-shopify-orders)
