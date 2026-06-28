import requests
import json

url = 'http://localhost:8080/api/v1/import/process'
files = {'file': open('test-data/inventory_dead_stock.csv', 'rb')}
data = {'mappingRule': json.dumps({"productName": "", "itemSku": ""}), 'userId': 'test_empty'}

r = requests.post(url, files=files, data=data)
print(r.status_code, r.text)
