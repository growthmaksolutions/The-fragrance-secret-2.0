#!/usr/bin/env python3
"""Put a list of products on offer, and take them off again.

An offer price in Shopify is not a separate field. Price lives on the variant
and is the same number everywhere — the offer page, the grid, search, the
cart. So "offer price" means moving two numbers:

    Compare-at price  <-  what the product costs normally
    Price             <-  what it costs during the offer

The theme reads exactly that: a variant whose compare-at is above its price
renders the original struck through, the new price beside it and a Save %
badge, on every surface the product appears.

── Two ways to say what the offer is ────────────────────────────────────

    handle,offer_price          handle,discount_percent
    9fm-edp-100ml,75            maryam-oil,20
                                dove-oil-ib,20

offer_price sets one exact price, so the product must have ONE variant.

discount_percent works on any product and is the one to use for the oils:
they carry four sizes at four different prices, and "20% off" prices each
size correctly where a single number cannot. Mixing both columns in one CSV
is fine — each row uses whichever cell is filled.

    python3 scripts/set-offer-prices.py offers.csv                  # dry run
    python3 scripts/set-offer-prices.py offers.csv --apply
    python3 scripts/set-offer-prices.py offers.csv --apply --tag sale
    python3 scripts/set-offer-prices.py offers.csv --apply --round 1

Nothing is written without --apply.

--tag adds a tag as well, which is how a product joins an automatic
collection: Crazy Deals is tag EQUALS sale, so --tag sale puts the product on
that page in the same pass that prices it.

--round snaps percentage results to whole dirhams (--round 1) or to .99
endings (--round 0.99). The default is exact, which can leave prices like
AED 63.20.

── Ending the offer ─────────────────────────────────────────────────────

Every applied run writes scripts/offer-rollback-<timestamp>.json holding each
variant's price, compare-at and tags exactly as they were. Giving that file
back puts them there again:

    python3 scripts/set-offer-prices.py --revert scripts/offer-rollback-<t>.json
    python3 scripts/set-offer-prices.py --revert scripts/offer-rollback-<t>.json --apply

This is the half that bulk pricing usually lacks. Marking 200 products down
takes one run; putting 200 products back without a record of what they cost
is guesswork, because by then the original price has BECOME the compare-at
price — and clearing the compare-at is exactly what ends the offer.

── What it refuses to do ────────────────────────────────────────────────

An offer at or above the current price, which is not an offer and would
render a struck-through number lower than the one beside it. A handle that
matches no product. An offer_price given for a product with several variants,
where "the price" is ambiguous — those are listed and skipped, with a note to
use discount_percent instead, rather than guessed at.

A product already marked down keeps its true original. If 9FM is AED 79 with
a compare-at of 100, a new offer of 75 shows "was 100", not "was 79" — the
first markdown must never become the second one's invented before-price.
"""

import argparse
import csv
import datetime
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "sct", os.path.join(HERE, "set-collection-templates.py"))
sct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sct)

GREEN, YELLOW, RED, DIM, RESET = sct.GREEN, sct.YELLOW, sct.RED, sct.DIM, sct.RESET

LOOKUP = """
query($handle: String!) {
  productByHandle(handle: $handle) {
    id title tags
    variants(first: 100) { nodes { id title price compareAtPrice } }
  }
}
"""

SET_PRICE = """
mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id price compareAtPrice }
    userErrors { field message }
  }
}
"""

ADD_TAGS = """
mutation($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) { userErrors { field message } }
}
"""

SET_TAGS = """
mutation($input: ProductInput!) {
  productUpdate(input: $input) { product { id } userErrors { field message } }
}
"""


def money(value):
    return "%.2f" % float(value)


def snap(value, step):
    """Round a percentage result to a tidy shelf price."""
    if not step:
        return round(value, 2)
    if abs(step - 0.99) < 1e-9:          # .99 endings: 63.20 -> 62.99
        return max(0.99, float(int(value)) - 0.01 if value % 1 < 0.99 else int(value) + 0.99)
    return round(round(value / step) * step, 2)


def read_csv(path):
    """Rows of (handle, offer_price|None, percent|None)."""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
        if "handle" not in cols:
            sys.exit("%sCSV needs a 'handle' column. Found: %s%s"
                     % (RED, reader.fieldnames, RESET))
        pct_col = next((cols[c] for c in cols if "percent" in c or c in ("pct", "discount")), None)
        price_col = next((cols[c] for c in cols
                          if "price" in c and cols[c] != pct_col), None)
        if not pct_col and not price_col:
            sys.exit("%sCSV needs an 'offer_price' or 'discount_percent' column.%s"
                     % (RED, RESET))
        for row in reader:
            handle = (row[cols["handle"]] or "").strip()
            if not handle:
                continue
            raw_pct = (row.get(pct_col) or "").strip() if pct_col else ""
            raw_price = (row.get(price_col) or "").strip() if price_col else ""
            if not raw_pct and not raw_price:
                continue
            rows.append((handle, raw_price or None, raw_pct or None))
    return rows


def original_of(variant):
    """What the variant normally costs, honouring an existing markdown."""
    price = float(variant["price"])
    was = variant.get("compareAtPrice")
    return float(was) if was and float(was) > price else price


def plan_offer(client, rows, step):
    """What each product would become. Nothing is written here."""
    changes, skips = [], []
    for handle, raw_price, raw_pct in rows:
        try:
            offer = float(raw_price) if raw_price else None
            pct = float(raw_pct) if raw_pct else None
        except ValueError:
            skips.append((handle, "price/percent is not a number"))
            continue
        if pct is not None and not 0 < pct < 100:
            skips.append((handle, "discount %g%% is not between 0 and 100" % pct))
            continue

        data = client.call(LOOKUP, {"handle": handle})
        product = data.get("productByHandle")
        if not product:
            skips.append((handle, "no product with this handle"))
            continue

        variants = product["variants"]["nodes"]
        if pct is None and len(variants) != 1:
            skips.append((handle, "%d variants — use discount_percent, not offer_price"
                          % len(variants)))
            continue

        planned, refused = [], None
        for variant in variants:
            current = float(variant["price"])
            original = original_of(variant)
            target = snap(original * (1 - pct / 100.0), step) if pct is not None else offer
            if target >= current:
                refused = ("offer %s is not below the current %s%s"
                           % (money(target), money(current),
                              " (%s)" % variant["title"] if len(variants) > 1 else ""))
                break
            planned.append({
                "variant_id": variant["id"],
                "title": variant["title"],
                "before": {"price": money(current),
                           "compare_at": money(variant["compareAtPrice"])
                           if variant.get("compareAtPrice") else None},
                "after": {"price": money(target), "compare_at": money(original)},
            })
        if refused:
            skips.append((handle, refused))
            continue

        first = planned[0]
        changes.append({
            "handle": handle,
            "title": product["title"],
            "product_id": product["id"],
            "tags_before": product["tags"],
            "variants": planned,
            "cut": round((float(first["after"]["compare_at"]) - float(first["after"]["price"]))
                         / float(first["after"]["compare_at"]) * 100)
            if float(first["after"]["compare_at"]) else 0,
        })
    return changes, skips


def write_variants(client, change, key):
    """Push either the 'after' or the 'before' side of a planned change."""
    return client.call(SET_PRICE, {
        "productId": change["product_id"],
        "variants": [{"id": v["variant_id"],
                      "price": v[key]["price"],
                      "compareAtPrice": v[key]["compare_at"]} for v in change["variants"]],
    })["productVariantsBulkUpdate"]


def apply_changes(client, changes, tag):
    done = 0
    for change in changes:
        result = write_variants(client, change, "after")
        if result["userErrors"]:
            print("  %s%s: %s%s" % (RED, change["handle"],
                                    json.dumps(result["userErrors"]), RESET))
            continue
        if tag and tag not in change["tags_before"]:
            client.call(ADD_TAGS, {"id": change["product_id"], "tags": [tag]})
        done += 1
    return done


def revert(client, path, apply):
    with open(path, encoding="utf-8") as handle:
        saved = json.load(handle)
    changes = saved["changes"]
    print("Restoring %d products from %s\n" % (len(changes), os.path.basename(path)))
    for change in changes:
        first = change["variants"][0]
        print("  %-44s %8s -> %-8s%s" % (change["title"][:44],
                                         first["after"]["price"], first["before"]["price"],
                                         "" if len(change["variants"]) == 1
                                         else "  (+%d more sizes)" % (len(change["variants"]) - 1)))
        if not apply:
            continue
        write_variants(client, change, "before")
        # Tags go back exactly as they were, so a tag the offer added is
        # removed and one the product already had is kept.
        client.call(SET_TAGS, {"input": {"id": change["product_id"],
                                         "tags": change["tags_before"]}})
    if apply:
        print("\n%sRestored.%s" % (GREEN, RESET))
    else:
        print("\n%sDry run — nothing was written. Re-run with --apply.%s" % (YELLOW, RESET))


def main():
    parser = argparse.ArgumentParser(
        description="Bulk offer pricing, with a rollback file so the offer can end.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", nargs="?", help="CSV of handle + offer_price or discount_percent")
    parser.add_argument("--revert", metavar="ROLLBACK", help="restore from a rollback file")
    parser.add_argument("--tag", help="also add this tag (e.g. sale, to join Crazy Deals)")
    parser.add_argument("--round", type=float, default=0, metavar="STEP", dest="step",
                        help="snap percentage results: 1 for whole dirhams, 0.99 for .99 endings")
    parser.add_argument("--apply", action="store_true",
                        help="write the changes (default is a dry run)")
    parser.add_argument("--token", help="Admin API token (defaults to .env)")
    args = parser.parse_args()

    dotenv = sct.load_dotenv()
    store = sct.credential(dotenv, "SHOPIFY_STORE_DOMAIN")
    token = args.token or sct.credential(dotenv, "SHOPIFY_ADMIN_ACCESS_TOKEN",
                                         "SHOPIFY_ADMIN_TOKEN")
    version = sct.credential(dotenv, "SHOPIFY_API_VERSION") or "2024-10"
    if not store or not token:
        sys.exit("No credentials found. Add SHOPIFY_STORE_DOMAIN and "
                 "SHOPIFY_ADMIN_ACCESS_TOKEN to .env")

    client = sct.Shopify(store, token, version)

    if args.revert:
        revert(client, args.revert, args.apply)
        return
    if not args.csv:
        parser.error("give a CSV of handle + offer_price/discount_percent, "
                     "or --revert a rollback file")

    rows = read_csv(args.csv)
    print("%s — %d rows, %s\n" % (os.path.basename(args.csv), len(rows),
                                  (GREEN + "APPLY" + RESET) if args.apply
                                  else (YELLOW + "dry run" + RESET)))

    changes, skips = plan_offer(client, rows, args.step)

    for change in changes:
        sizes = "" if len(change["variants"]) == 1 \
            else "%s  (%d sizes)%s" % (DIM, len(change["variants"]), RESET)
        first = change["variants"][0]
        print("  %-42s %8s -> %-8s %s-%d%%%s %s"
              % (change["title"][:42], first["after"]["compare_at"],
                 first["after"]["price"], GREEN, change["cut"], RESET, sizes))
    for handle, why in skips:
        print("  %s%-42s skipped: %s%s" % (YELLOW, handle[:42], why, RESET))

    print("\n%d to price, %d skipped" % (len(changes), len(skips)))
    if args.tag:
        adding = sum(1 for c in changes if args.tag not in c["tags_before"])
        print("%d would also be tagged %r" % (adding, args.tag))

    if not args.apply:
        print("\n%sDry run — nothing was written. Re-run with --apply.%s" % (YELLOW, RESET))
        return
    if not changes:
        print("\nNothing to do.")
        return

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    rollback = os.path.join(HERE, "offer-rollback-%s.json" % stamp)
    with open(rollback, "w", encoding="utf-8") as handle:
        json.dump({"created": stamp, "tag": args.tag, "changes": changes}, handle, indent=1)

    done = apply_changes(client, changes, args.tag)
    print("\n%sPriced %d products.%s" % (GREEN, done, RESET))
    print("Rollback written to %s" % rollback)
    print("End the offer with:\n  python3 scripts/set-offer-prices.py --revert %s --apply"
          % rollback)


if __name__ == "__main__":
    main()
