"""
Download NYC and Albany Airbnb reviews from Inside Airbnb (February 2026).

Run:
    python download_data.py
"""

import gzip
import os
import shutil
import urllib.request

URLS = {
    "reviews_2026_feb_albany.csv": "https://data.insideairbnb.com/united-states/ny/albany/2026-02-15/data/reviews.csv.gz",
    "reviews_2026_feb_nyc.csv": "https://data.insideairbnb.com/united-states/ny/new-york-city/2026-02-13/data/reviews.csv.gz",
}

os.makedirs("data", exist_ok=True)

for filename, url in URLS.items():
    dest = os.path.join("data", filename)
    if os.path.exists(dest):
        print(f"Already exists: {dest}")
        continue

    gz_path = dest + ".gz"
    print(f"Downloading {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response, open(gz_path, "wb") as f:
        shutil.copyfileobj(response, f)

    with gzip.open(gz_path, "rb") as f_in, open(dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(gz_path)

    size_mb = os.path.getsize(dest) / 1_000_000
    print(f"Saved {dest} ({size_mb:.1f} MB)")

print("Done.")
