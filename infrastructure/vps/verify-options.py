"""Read-only live checks. Does not create Telegram messages or orders."""
import json
import urllib.request

base = 'http://127.0.0.1:18080'
health = json.loads(urllib.request.urlopen(base+'/health', timeout=5).read())
assert 'product_options' in health.get('features', []), health
for url in (
    'https://www.zara.com/es/en/combined-satin-trousers-p08912573.html?v1=594839492&v2=2420795',
    'https://www.zara.com/es/en/basic-plush-trousers-p03199635.html?v1=594401162&v2=2419265',
):
    request = urllib.request.Request(base+'/product', data=json.dumps({'url': url}).encode(),
                                     headers={'Content-Type': 'application/json'})
    result = json.loads(urllib.request.urlopen(request, timeout=65).read())
    assert result.get('price_eur'), result
    colors = result.get('variants') or []
    assert colors and any(c.get('sizes') for c in colors), result
    print(json.dumps({
        'name': result.get('name'), 'price_eur': result['price_eur'],
        'colors': [{ 'name': c['name'], 'sizes': [s['name'] for s in c['sizes']] } for c in colors],
    }, ensure_ascii=False), flush=True)
print('PRODUCT_OPTIONS_READY', flush=True)
