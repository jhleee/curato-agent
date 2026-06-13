import requests
from bs4 import BeautifulSoup

urls = [
    'https://media.naver.com/press/001/issue',
    'https://media.naver.com/issue/092/492'
]

for url in urls:
    resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(resp.text, 'html.parser')
    print(f"\nURL: {url}")
    print(f"Title: {soup.title.string if soup.title else 'No Title'}")
    
    links = soup.select('a[href]')
    print(f"Total links: {len(links)}")
    
    article_links = [l['href'] for l in links if 'article/' in l['href']]
    print(f"Article links: {len(article_links)}")
    for l in list(set(article_links))[:5]:
        print(" ", l)
