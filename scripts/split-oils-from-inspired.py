#!/usr/bin/env python3
"""Move the perfume oils out of Inspired Perfumes and into Perfume Oil.

Both are smart collections, so this changes two rule sets rather than
retagging 123 products. The products are not touched at all.

Why titles and not tags. The oil tag is spelled three ways in the catalogue —
'perfume oil' (70), 'perfume-oil' (21) and a typo, 'Perfum Oil' (9 products
carry only that one). A rule set written against tags has to chase all three
and breaks again the next time someone types a fourth. Every one of these
products says "Perfume Oil" in its title, so the title is the reliable signal
and the tags are kept only as an OR, to catch the attars whose titles say
"Attar" and never "Perfume Oil".

    python3 scripts/split-oils-from-inspired.py           # dry run
    python3 scripts/split-oils-from-inspired.py --apply

Nothing is written without --apply. Needs read_products and write_products.
"""
import argparse, io, json, re, ssl, sys, urllib.request

ROOT = '/Users/admin/Documents/The-fragrance-secret-2.0/'
env = {}
for line in io.open(ROOT + '.env', encoding='utf-8'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1); env[k.strip()] = v.strip()
DOM, TOK = env['SHOPIFY_STORE_DOMAIN'], env['SHOPIFY_ADMIN_ACCESS_TOKEN']
CTX = ssl.create_default_context(cafile='/etc/ssl/cert.pem')
URL = f'https://{DOM}/admin/api/2024-10/graphql.json'

# The local resolver has been intermittently failing on the shop domain while
# public DNS answers fine, so the IP is pinned rather than left to chance.
import socket
_orig = socket.getaddrinfo
def _pinned(host, *a, **k):
    if host == DOM: return _orig('23.227.38.74', *a, **k)
    return _orig(host, *a, **k)
socket.getaddrinfo = _pinned

def call(q, v=None):
    body = json.dumps({'query': q, 'variables': v or {}}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        'X-Shopify-Access-Token': TOK, 'Content-Type': 'application/json'})
    d = json.load(urllib.request.urlopen(req, timeout=60, context=CTX))
    if 'errors' in d: sys.exit('GraphQL error: ' + json.dumps(d['errors'])[:400])
    return d['data']

OILS = 'Perfume Oil'
# ANY of these. The title carries the 123 that are moving plus every other
# oil; the tags carry the attars, whose titles say "Attar" and never "Oil".
OIL_RULES = [
    {'column': 'TITLE', 'relation': 'CONTAINS',  'condition': OILS},
    {'column': 'TAG',   'relation': 'EQUALS',    'condition': 'perfume oil'},
    {'column': 'TAG',   'relation': 'EQUALS',    'condition': 'perfume-oil'},
    {'column': 'TAG',   'relation': 'EQUALS',    'condition': 'Perfum Oil'},
]
# ALL of these. One exclusion instead of three, and it does not care how the
# oil was tagged.
INSPIRED_RULES = [
    {'column': 'TAG',   'relation': 'EQUALS',       'condition': 'Inspired'},
    {'column': 'TITLE', 'relation': 'NOT_CONTAINS', 'condition': OILS},
]

PLAN = [
    ('perfume-oil',       OIL_RULES,      True,  'Perfume Oil'),
    ('inspired-perfumes', INSPIRED_RULES, False, 'Inspired Perfumes'),
]

Q_FIND = '''query($h:String!){collectionByHandle(handle:$h){
  id title productsCount{count}
  ruleSet{ appliedDisjunctively rules{ column relation condition } }}}'''

M_UPDATE = '''mutation($input:CollectionInput!){collectionUpdate(input:$input){
  collection{ id title productsCount{count} }
  userErrors{ field message }}}'''

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    for handle, rules, disjunctive, label in PLAN:
        c = call(Q_FIND, {'h': handle})['collectionByHandle']
        if not c: sys.exit(f'no collection with handle {handle!r}')
        rs = c.get('ruleSet') or {}
        print(f"\n{c['title']}  (/{handle})  — {c['productsCount']['count']} products now")
        print('  current rules (%s):' % ('ANY' if rs.get('appliedDisjunctively') else 'ALL'))
        for r in rs.get('rules', []):
            print(f"      {r['column']} {r['relation']} {r['condition']!r}")
        print('  proposed rules (%s):' % ('ANY' if disjunctive else 'ALL'))
        for r in rules:
            print(f"      {r['column']} {r['relation']} {r['condition']!r}")
        if not args.apply:
            continue
        res = call(M_UPDATE, {'input': {
            'id': c['id'],
            'ruleSet': {'appliedDisjunctively': disjunctive, 'rules': rules}}})
        errs = res['collectionUpdate']['userErrors']
        if errs: sys.exit('Shopify rejected it: ' + json.dumps(errs, indent=2))
        after = res['collectionUpdate']['collection']['productsCount']['count']
        print(f"  -> updated. {c['productsCount']['count']} products becomes {after}")

    if not args.apply:
        print('\nDry run — nothing was written. Re-run with --apply.')

main()
