import json
import urllib.request

print('BROWSER_HEALTH',urllib.request.urlopen('http://127.0.0.1:18080/health',timeout=5).read().decode(),flush=True)
for url in [
 'https://www.zara.com/es/en/combined-satin-trousers-p08912573.html?v1=594839492&v2=2420795',
 'https://www.zara.com/es/en/basic-plush-trousers-p03199635.html?v1=594401162&v2=2419265',
]:
 request=urllib.request.Request('http://127.0.0.1:18080/product',data=json.dumps({'url':url}).encode(),headers={'Content-Type':'application/json'})
 result=json.loads(urllib.request.urlopen(request,timeout=65).read())
 print('PRODUCT_RESULT',json.dumps(result,ensure_ascii=False),flush=True)
 if not result.get('price_eur'):
  raise SystemExit('Цена не получена. Бот не переключать; требуется проверка.')
print('VPS_BROWSER_READY',flush=True)
