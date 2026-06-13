import time
import random
from itertools import cycle
import requests

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.4 Safari/605.1.15",

    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
]

ua_cycle = cycle(USER_AGENTS)

def get_with_delay(url: str, min_delay: float = 1.0, max_delay: float = 3.0):
    time.sleep(random.uniform(min_delay, max_delay))
    headers = {"User-Agent": next(ua_cycle)}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response
