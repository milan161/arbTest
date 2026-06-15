import urllib.request
url = "http://hq.sinajs.cn/list=hf_ES"
req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn/'}, method='GET')
with urllib.request.urlopen(req, timeout=15) as response:
    print(response.read().decode('gbk'))
