import requests
from bs4 import BeautifulSoup

url = 'https://n.news.naver.com/article/print/092/0002426443'
resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(resp.text, 'html.parser')

print(f"URL: {url}")
title_tag = soup.select_one('.media_end_head_headline, h3')
title = title_tag.text.strip() if title_tag else 'No Title'
print(f"Title: {title}")

# In print view, the body is usually inside #articeBody
body_tag = soup.select_one('#articeBody, #dic_area')
if body_tag:
    body_text = ' '.join(body_tag.stripped_strings)
    print(f"Body length: {len(body_text)}")
    print(f"Body preview: {body_text[:200]}")
else:
    print("Body not found")
