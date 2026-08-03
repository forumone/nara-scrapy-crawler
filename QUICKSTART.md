# Quickstart

Minimal commands to confirm the crawler works on your machine. Two of the
simplest sites: `open_obama_whitehouse` (no sitemap, single fused spider)
and `clintonwhitehouse1` (sitemap-based, two-phase).

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## open_obama_whitehouse

Single spider, harvests + scrapes in one pass, a few hundred pages.

```bash
scrapy crawl open_obama_whitehouse
```

Writes `data/open.obamawhitehouse/open.obamawhitehouse_harvest.csv` and
`data/open.obamawhitehouse/open.obamawhitehouse.csv`.

## clintonwhitehouse1

Sitemap-based, two phases.

```bash
scrapy crawl sitemap_harvest \
  -a sitemap_url=https://clintonwhitehouse1.archives.gov/sitemap.xml \
  -a source_site=clintonwhitehouse1

scrapy crawl clintonwhitehouse1 \
  -a url_file=data/clintonwhitehouse1/clintonwhitehouse1_harvest.csv
```

Writes `data/clintonwhitehouse1/clintonwhitehouse1_harvest.csv` and
`data/clintonwhitehouse1/clintonwhitehouse1.csv`.

If both produce a non-empty `.csv` with real title/body content, the
environment is set up correctly. See README.md and HARVESTING.md for the
full picture.
