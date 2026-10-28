#!/usr/bin/env python3
"""Open the filterable product metafields to the storefront.

Collection pages offer one filter, brand, because every other candidate
metafield is defined with storefront access NONE. Search & Discovery can only
offer a metafield as a filter if the storefront is allowed to read it, so the
fields never appear in its filter list to be switched on.

This sets access.storefront = PUBLIC_READ on the eight whose values are clean
enough to filter by. It does NOT create the filters: Shopify has no Admin API
for Search & Discovery's filter configuration, so the last step is a human in
admin. This removes the reason that step currently cannot be taken.

Only these eight, and the reason is cardinality rather than preference. A
filter is useful when many products share a value. Sampled over 250 active
products:

    gender          3 distinct     Unisex / Men / Women
    concentration   3 distinct     Eau de Parfum / EDT / Parfum
    longevity       2 distinct     Long Lasting / Very Long Lasting
    sillage         3 distinct     Moderate to Strong / Strong / Moderate
    product_form    4 distinct     Eau de Parfum / EDT / Gift Set / ...
    origin          7 distinct     UAE / France / USA / ...
    best_for        8 distinct     Everyday & Evening / Evening & Formal / ...
    size           10 distinct     100ML / 120ML / 75ML / ...

Deliberately excluded, because each holds a comma-joined list in one text
field and would generate a filter with one option per product:

    notes_top      178 distinct over 199 products
    fragrance_family 151 distinct over 200 products
    occasion        16 distinct, but the values are long comma strings that
                    read badly as filter labels

Those need converting to list.single_line_text_field before they can filter,
which is a data migration and a separate job.

Nothing exposed here is private: all eight are product attributes the product
page already prints.

    python3 scripts/enable-storefront-filters.py           # dry run
    python3 scripts/enable-storefront-filters.py --apply

Nothing is written without --apply. Needs write_metafield_definitions.
"""
import argparse, io, json, socket, ssl, sys, urllib.request

ROOT = '/Users/admin/Documents/The-fragrance-secret-2.0/'
env = {}
for line in io.open(ROOT + '.env', encoding='utf-8'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1); env[k.strip()] = v.strip()
DOM, TOK = env['SHOPIFY_STORE_DOMAIN'], env['SHOPIFY_ADMIN_ACCESS_TOKEN']
CTX = ssl.create_default_context(cafile='/etc/ssl/cert.pem')
URL = f'https://{DOM}/admin/api/2024-10/graphql.json'

# The local resolver fails on the shop domain intermittently while public DNS
# answers; pin it rather than leave the run to chance.
_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, *a, **k: _orig('23.227.38.74', *a, **k) if h == DOM else _orig(h, *a, **k)

KEYS = ['gender', 'concentration', 'longevity', 'sillage',
        'product_form', 'origin', 'best_for', 'size']
NS = 'custom'

def call(q, v=None):
    body = json.dumps({'query': q, 'variables': v or {}}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        'X-Shopify-Access-Token': TOK, 'Content-Type': 'application/json'})
    d = json.load(urllib.request.urlopen(req, timeout=60, context=CTX))
    if 'errors' in d: sys.exit('GraphQL error: ' + json.dumps(d['errors'])[:400])
    return d['data']

Q = '''{ metafieldDefinitions(first:50, ownerType: PRODUCT, namespace:"%s"){
  edges{node{ id key name access{ storefront } }}}}''' % NS

M = '''mutation($d: MetafieldDefinitionUpdateInput!){
  metafieldDefinitionUpdate(definition:$d){
    updatedDefinition{ key access{ storefront } }
    userErrors{ field message }}}'''

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    defs = {e['node']['key']: e['node']
            for e in call(Q)['metafieldDefinitions']['edges']}

    todo, already, missing = [], [], []
    for k in KEYS:
        d = defs.get(k)
        if not d: missing.append(k)
        elif d['access']['storefront'] == 'PUBLIC_READ': already.append(k)
        else: todo.append(d)

    print('%-18s %s' % ('metafield', 'storefront access'))
    for d in todo:    print('%-18s %s -> PUBLIC_READ' % (d['key'], d['access']['storefront']))
    for k in already: print('%-18s already PUBLIC_READ, skipped' % k)
    for k in missing: print('%-18s NO SUCH DEFINITION' % k)

    if not args.apply:
        print('\nDry run — nothing was written. Re-run with --apply.')
        return

    for d in todo:
        r = call(M, {'d': {'namespace': NS, 'key': d['key'], 'ownerType': 'PRODUCT',
                           'access': {'storefront': 'PUBLIC_READ'}}})
        errs = r['metafieldDefinitionUpdate']['userErrors']
        if errs:
            print('  %-16s REJECTED: %s' % (d['key'], json.dumps(errs)))
            continue
        got = r['metafieldDefinitionUpdate']['updatedDefinition']['access']['storefront']
        print('  %-16s now %s' % (d['key'], got))

main()
