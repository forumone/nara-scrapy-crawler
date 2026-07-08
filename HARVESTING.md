# Harvesting a New No-Sitemap Site

This document describes the end-to-end process for adding a new no-sitemap site
to the crawl pipeline. The two-phase approach (harvest URLs first, scrape content
second) allows for auditing the full URL list before any content is fetched,
making coverage gaps and unexpected pages visible before they become data problems.

---

## Choosing a harvester pattern

**Use `generic_crawl_harvest`** for small, simple sites. It follows `?page=`/`/page/`-style
pagination automatically (without recording the listing pages themselves as content —
only the content links found on them), so ordinary paginated listing sections don't
by themselves require the split pattern anymore.

**Use the split harvester pattern** (`*_harvest_list` + `*_harvest_nav`) when a site's
pagination doesn't follow the `?page=`/`/page/` convention (custom offset/cursor
params, JS-driven infinite scroll, etc.), or when listing rows need a specific CSS
selector to identify the real content link rather than generic link-following. The
nav spider alone will miss content behind pagination; the list spider alone will
miss nav-only pages.

If you are not sure, start with site discovery (step 1) and try `generic_crawl_harvest`
first — if the pagination doesn't match the standard convention or content links can't
be reliably distinguished from navigation/facet noise, fall back to the split pattern.

---

## Step-by-step: split harvester

### Step 1 — Discovery

Inspect the live site to answer these questions before writing any code:

- What are the paginated listing sections? (blog, news, press releases, etc.)
  Look for pagination controls and note the URL pattern for page 2+.
- What CSS selector identifies a content link within a listing row?
  (e.g. `.views-row .views-field-title a`, `article h3 a`)
- What are the top-level nav sections? These become `start_urls` for the nav spider.
- Are there path prefixes that should be excluded from the nav crawl?
  (e.g. `/sites/` for Drupal assets, `/user/`, `/print/`, `/category/`)
- What is the domain? Are there subdomains that should be handled by separate spiders?

### Step 2 — Harvest listing pages

Create `archive_crawler/spiders/<site>_harvest_list.py`. This is a plain
`scrapy.Spider` that paginates through each listing section and yields one
`{'url': href}` per content link found.

```python
import scrapy

class MySiteHarvestListSpider(scrapy.Spider):
    name = "mysite_harvest_list"
    allowed_domains = ["example.archives.gov"]
    start_urls = [
        "https://example.archives.gov/blog/",
        "https://example.archives.gov/news/",
    ]

    def parse(self, response):
        for href in response.css('.views-row .views-field-title a::attr(href)').getall():
            yield {'url': response.urljoin(href)}

        next_page = response.css('.pager-next a::attr(href)').get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)
```

Run it:

```
scrapy crawl mysite_harvest_list -o data/mysite/mysite_harvest_list.csv
```

Inspect the output before continuing. Verify row count is plausible and spot-check
a sample of URLs to confirm they point to individual content pages, not listing pages.

### Step 3 — Harvest nav pages

Create `archive_crawler/spiders/<site>_harvest_nav.py` using `NavHarvesterMixin`.
The list harvest from step 2 **must** be passed as `listing_file` — the nav spider
will not run without it. This ensures the nav spider skips all URLs already captured
by the list harvester and does not recurse into listing sections.

```python
from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule
from archive_crawler.spiders.base import NavHarvesterMixin

class MySiteHarvestNavSpider(NavHarvesterMixin, CrawlSpider):
    name = "mysite_harvest_nav"
    allowed_domains = ["example.archives.gov"]
    start_urls = [
        "https://example.archives.gov/",
        "https://example.archives.gov/about/",
        # ... top-level nav sections identified in step 1
    ]

    rules = (
        Rule(
            LinkExtractor(
                allow=r'//example\.archives\.gov/',
                allow_domains=['example.archives.gov'],
                deny=(r'/sites/', r'/user/', r'/print/'),
            ),
            callback='parse_nav',
            follow=False,
        ),
    )
```

Run it, feeding the list harvest:

```
scrapy crawl mysite_harvest_nav \
    -a listing_file=data/mysite/mysite_harvest_list.csv \
    -o data/mysite/mysite_harvest_nav.csv
```

The default `DEPTH_LIMIT` is 2. If spot-checking reveals genuine content pages are
missing, increase it by overriding `custom_settings` in the spider and re-running.
Start at 2, try 3, then 4. Beyond 4 the crawl becomes slow and the marginal return
is usually low.

### Step 4 — Merge

```
python merge_harvest.py \
    data/mysite/mysite_harvest_nav.csv \
    data/mysite/mysite_harvest_list.csv \
    -o data/mysite/mysite_harvest_full.csv
```

Compare the merged URL count against any existing scrape results. Investigate
unexpectedly large gaps before proceeding. Categories of expected non-matches:

- **In existing but not harvest**: check for listing pages, mangled URLs, or
  genuinely unreachable content (403s, 404s). Only the last category is a real gap.
- **In harvest but not existing**: these are new URLs the previous crawl missed.
  Spot-check a sample to confirm they are real content pages, not noise.

### Step 5 — Scrape

Create `archive_crawler/spiders/<site>.py` using `ArchiveSpiderMixin`. It reads
from `url_file` (the merged harvest CSV) and extracts title, body, and teaser.

```python
import csv
import scrapy
from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin

class MySiteSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "mysite"
    SOURCE_SITE = 'mysite'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError("url_file argument is required: -a url_file=data/mysite/mysite_harvest_full.csv")
        with open(url_file, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                yield scrapy.Request(row['url'], callback=self.parse_item)

    def parse_item(self, response):
        body = self._extract_text(response, '#maincontent .content')
        if not body:
            return
        title = response.css('h1').xpath('string(.)').get(default='').strip()
        if not title:
            return
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item
```

Run it:

```
scrapy crawl mysite \
    -a url_file=data/mysite/mysite_harvest_full.csv \
    -o data/mysite/mysite.csv
```

---

## Step-by-step: generic harvester

For simple sites, skip to a single harvest phase:

```
scrapy crawl generic_crawl_harvest \
    -a url=https://example.archives.gov/ \
    -a urls_to_skip='/print/,/user/,/node/\d' \
    -o data/example/example_harvest.csv
```

`?page=`/`/page/` links are followed but not recorded as content. Every followed
link also has its query string reduced to just the pagination param, if present —
Scrapy's duplicate-request filter then collapses facet/sort/tracking-decorated
variants of the same page into a single crawl. This does not stop distinct facet
*paths* (e.g. chained `/field_tags/X/field_tags/Y/` segments on faceted-search
sites) from each being crawled once each — block those per-site with `urls_to_skip`
(e.g. `-a urls_to_skip='/field_tags/,/search/'`).

Then scrape using `generic_crawl` or a custom scraper spider:

```
scrapy crawl generic_crawl \
    -a url_file=data/example/example_harvest.csv \
    -a site_id=example \
    -a source_type='Archived White House Websites' \
    -o data/example/example.csv
```

`generic_crawl`'s selectors (`crawl_spider.py`) are a union tuned to the site
templates already seen in this repo, not a universal HTML-content detector. A new
site's first run commonly yields zero items — extend the XPath union or subclass
with site-specific selectors, same as any other new site's scraper.

---

## Naming conventions

| File | Spider name |
|---|---|
| `<site>_harvest_list.py` | `<site>_harvest_list` |
| `<site>_harvest_nav.py` | `<site>_harvest_nav` |
| `<site>.py` | `<site>` |
| Output CSVs | `data/<site>/<site>_harvest_list.csv`, `data/<site>/<site>_harvest_nav.csv`, `data/<site>/<site>_harvest_full.csv`, `data/<site>/<site>.csv` |

Use the `source_site` value as `<site>` (e.g. `letsmove.obamawhitehouse`,
`petitions.trumpwhitehouse`). Dots in the source_site become dots in filenames.
