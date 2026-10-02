"""Download index constituents from Yahoo Finance: python scripts/yahoo_constituents.py ^DJI ^NDX ...
Writes data/constituents/<index>.csv. Yahoo returns an empty list for some indices (e.g. ^GSPC)."""
import csv, json, sys, urllib.parse, urllib.request
from http.cookiejar import CookieJar

op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
op.addheaders = [("User-Agent", "Mozilla/5.0")]
try: op.open("https://fc.yahoo.com", timeout=20)
except Exception: pass  # fc.yahoo.com 404s but sets the cookie
crumb = op.open("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=20).read().decode()

for idx in sys.argv[1:]:
    q = urllib.parse.urlencode({"modules": "components", "formatted": "false", "crumb": crumb})
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(idx)}?{q}"
    syms = json.load(op.open(url, timeout=30))["quoteSummary"]["result"][0]["components"]["components"]
    if not syms: print(idx, "empty"); continue
    with open(f"data/constituents/{idx.lstrip('^')}.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["symbol"]); w.writerows([s] for s in syms)
    print(idx, len(syms))
