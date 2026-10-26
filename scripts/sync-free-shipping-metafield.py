#!/usr/bin/env python3
"""Stamp products that ship free unconditionally, so the storefront can say so.

The product page tells a shopper "free over AED 250". For most of the
catalogue that is right. For the products in a free-shipping delivery
profile it is wrong — those ship free at any order value, so the page
understates its own offer and a shopper buying one AED 110 bottle thinks
they are about to pay a delivery fee they will never be charged.

The storefront cannot work this out for itself. Liquid has no access to
delivery profiles at all: there is no `product.delivery_profile`, and
nothing in the product object says which rates apply to it. Product type
does not stand in for it either — the "Free shipping for Oil" profile is
entirely type Oil, but four more Oil products sit in a different profile
with different rates, so matching on type would make the claim wrong for
exactly the products it is meant to fix.

So the fact has to be carried to the storefront as data. This reads the
delivery profiles, works out which products ship free to the UAE with no
minimum, and writes a boolean metafield the theme reads:

    custom.free_shipping = true

Products that fall out of such a profile have the metafield set back to
false rather than deleted, so a stale `true` can never outlive the rate
that justified it.

Read-only by default. Nothing is written without --apply.

    python3 scripts/sync-free-shipping-metafield.py            # report
    python3 scripts/sync-free-shipping-metafield.py --apply    # write

Re-run it after any change to Settings > Shipping and delivery. Nothing
keeps these in step automatically, which is the weakness of the approach
and the reason the report prints what it would change every time.
"""

import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "sct", os.path.join(HERE, "set-collection-templates.py"))
sct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sct)

GREEN, YELLOW, RED, DIM, RESET = sct.GREEN, sct.YELLOW, sct.RED, sct.DIM, sct.RESET

HOME_COUNTRY = "AE"

PROFILES = """
{
  deliveryProfiles(first: 20) {
    nodes {
      id
      name
      default
      profileLocationGroups {
        locationGroupZones(first: 30) {
          nodes {
            zone { countries { code { countryCode } } }
            methodDefinitions(first: 30) {
              nodes {
                active
                rateProvider {
                  __typename
                  ... on DeliveryRateDefinition { price { amount } }
                }
                methodConditions { field operator }
              }
            }
          }
        }
      }
    }
  }
}
"""

PROFILE_ITEMS = """
query($id: ID!, $cursor: String) {
  deliveryProfile(id: $id) {
    profileItems(first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        product {
          id
          handle
          status
          metafield(namespace: "custom", key: "free_shipping") { value }
        }
      }
    }
  }
}
"""

SET_METAFIELDS = """
mutation($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    userErrors { field message }
  }
}
"""


def ships_free_unconditionally(profile):
    """True when this profile delivers to the home country at zero cost with
    no minimum-order condition attached.

    A rate with conditions is not this: "Free delivery over AED 250" is a
    zero-cost rate too, and treating it as unconditional is precisely the
    mistake the storefront is already making."""
    for group in profile["profileLocationGroups"]:
        for zone in group["locationGroupZones"]["nodes"]:
            codes = {c["code"]["countryCode"] for c in zone["zone"]["countries"]}
            if HOME_COUNTRY not in codes:
                continue
            for method in zone["methodDefinitions"]["nodes"]:
                if not method["active"]:
                    continue
                if method.get("methodConditions"):
                    continue                       # has a threshold — not unconditional
                provider = method.get("rateProvider") or {}
                price = (provider.get("price") or {}).get("amount")
                if price is not None and float(price) == 0.0:
                    return True
    return False


def profile_products(client, profile_id):
    cursor, out = None, []
    while True:
        data = client.call(PROFILE_ITEMS, {"id": profile_id, "cursor": cursor})
        items = data["deliveryProfile"]["profileItems"]
        for node in items["nodes"]:
            if node["product"]:
                out.append(node["product"])
        if not items["pageInfo"]["hasNextPage"]:
            return out
        cursor = items["pageInfo"]["endCursor"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="write the metafields; without it nothing is changed")
    args = parser.parse_args()

    dotenv = sct.load_dotenv()
    store = sct.credential(dotenv, "SHOPIFY_STORE_DOMAIN")
    token = sct.credential(dotenv, "SHOPIFY_ADMIN_ACCESS_TOKEN")
    version = sct.credential(dotenv, "SHOPIFY_API_VERSION") or sct.DEFAULT_API_VERSION
    if not store or not token:
        sys.exit("%sSHOPIFY_STORE_DOMAIN and SHOPIFY_ADMIN_ACCESS_TOKEN must be set%s" % (RED, RESET))

    client = sct.Shopify(store, token, version)
    profiles = client.call(PROFILES)["deliveryProfiles"]["nodes"]

    free_ids, paid_ids = [], []
    print("%sDelivery profiles%s" % (DIM, RESET))
    for profile in profiles:
        free = ships_free_unconditionally(profile)
        (free_ids if free else paid_ids).append(profile)
        mark = "%sfree, no minimum%s" % (GREEN, RESET) if free else "%sconditional or paid%s" % (DIM, RESET)
        print("  %-44s %s" % (profile["name"][:44], mark))

    want_true, want_false = {}, {}
    for profile in free_ids:
        for product in profile_products(client, profile["id"]):
            want_true[product["id"]] = product
    for profile in paid_ids:
        for product in profile_products(client, profile["id"]):
            if product["id"] not in want_true:
                want_false[product["id"]] = product

    def current(product):
        mf = product.get("metafield")
        return (mf or {}).get("value") == "true"

    to_set = [p for p in want_true.values() if not current(p)]
    to_clear = [p for p in want_false.values() if current(p)]

    print("\n%sProducts shipping free with no minimum: %d%s" % (DIM, len(want_true), RESET))
    for product in to_set[:15]:
        print("  %s+%s %s" % (GREEN, RESET, product["handle"][:70]))
    if len(to_set) > 15:
        print("  %s… and %d more%s" % (DIM, len(to_set) - 15, RESET))
    for product in to_clear[:15]:
        print("  %s-%s %s %s(no longer free)%s" % (YELLOW, RESET, product["handle"][:60], DIM, RESET))

    if not to_set and not to_clear:
        print("\n%sNothing to change — the metafields already match the profiles.%s" % (GREEN, RESET))
        return

    print("\n%d to set true, %d to set false." % (len(to_set), len(to_clear)))
    if not args.apply:
        print("%sDry run. Re-run with --apply to write.%s" % (YELLOW, RESET))
        return

    payload = []
    for product in to_set:
        payload.append({"ownerId": product["id"], "namespace": "custom", "key": "free_shipping",
                        "type": "boolean", "value": "true"})
    for product in to_clear:
        payload.append({"ownerId": product["id"], "namespace": "custom", "key": "free_shipping",
                        "type": "boolean", "value": "false"})

    written = 0
    for i in range(0, len(payload), 25):            # metafieldsSet caps at 25
        batch = payload[i:i + 25]
        result = client.call(SET_METAFIELDS, {"metafields": batch})
        errors = result["metafieldsSet"]["userErrors"]
        if errors:
            sys.exit("%smetafieldsSet failed:%s %s" % (RED, RESET, errors))
        written += len(batch)
        print("  wrote %d/%d" % (written, len(payload)))

    print("%sDone. The storefront reads custom.free_shipping on the next render.%s" % (GREEN, RESET))


if __name__ == "__main__":
    main()
