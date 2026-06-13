import requests
import re
url = 'https://media.naver.com/press/001/issue'
resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
links = re.findall(r'href=[\'\"]?([^\'\"\s>]+)[\'\"]?', resp.text)
articles = [l for l in links if '/article/' in l]
print('Found articles?', len(articles))
print('Total text length:', len(resp.text))
print('Sample links:', [l for l in links if 'naver.com' in l][:5])
