"""
Generic scraper spider — phase 2 of the two-phase crawl workflow.

Reads the URL CSV produced by generic_crawl_harvest and extracts title,
body, and teaser from each page. Output is an ArchiveItem CSV suitable
for ingest.

Usage
-----
After running generic_crawl_harvest:

    scrapy crawl generic_crawl \
        -a url_file=data/example_harvest.csv \
        -a site_id=example.site \
        -a source_type='Archived White House Websites' \
        -o data/example.csv

Arguments
---------
url_file    Required. Path to the harvest CSV (must have a 'url' column).
site_id     Required in practice; defaults to 'archive'. Populates the
            source_site field in the output. Use the SOURCE_SITE convention
            from the other spiders (e.g. 'letsmove.obamawhitehouse').
source_type Optional. Populates source_type in the output. Typically
            'Archived White House Websites'.

Customising for a new site
--------------------------
The title_xpath and body_xpath cover the layouts seen across existing
sites. For a new site, inspect the page structure and extend the XPath
union expressions, or subclass and override parse_item entirely. The
two-phase contract is: start_requests reads the CSV, parse_item handles
one page, yields one ArchiveItem per page (flagged via 'warnings' rather
than dropped when title/body extraction comes up empty or thin).
"""
import csv
import re

import scrapy
from scrapy.selector import Selector
from w3lib.html import remove_tags_with_content

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class GenericCrawlSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "generic_crawl"

    def __init__(self, url_file=None, site_id='archive', source_type='', *args, **kwargs):
        if not url_file:
            raise ValueError("url_file argument is required: -a url_file=path/to/harvest.csv")
        self.url_file = url_file
        self.site_id = site_id
        self.SOURCE_SITE = site_id
        self.source_type = source_type
        super().__init__(*args, **kwargs)

    def start_requests(self):
        with open(self.url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                yield scrapy.Request(row['url'], callback=self.parse_item)

    def parse_item(self, response):
        if self._is_excluded_response(response):
            return
        warnings = []

        body_xpath = (
            "//div[contains(@class, 'hero-page-content')]"
            " | //div[@id='maincontent']/*/div[@class='content']"
            " | //div[starts-with(@id, 'node-')]/div/p"
            " | //div[contains(@class, 'pane-bundle-forall-checklist')]"
            " | //div[contains(@class, 'forall-body')]"
            " | //div[@id='microsite']"
            " | //div[contains(@class,'longpage-section')]"
            " | //div[contains(@class, 'field-name-body')]"
        )
        match_body = response.xpath(body_xpath).get()
        try:
            cleaned = remove_tags_with_content(match_body, which_ones=('script', 'style'))
        except TypeError:
            cleaned = ''
        raw_body = Selector(text=cleaned).xpath('string(.)').get(default='')
        body = re.sub(r'\s+', ' ', raw_body).strip()
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')

        title_xpath = (
            "//div[@id='hero-caption']//h1"
            " | //h1[@class='maincontent_title']"
            " | //*[@id='maincontent']/div/div[1]/h2"
            " | //*[@id='maincontent']/h1"
            " | //h1[@class='title'][normalize-space()]"
            " | //div[contains(@class, 'pane-whr-achievement-page-intro-pane')]//h1"
        )
        default_title = response.xpath('//head/title[1]').xpath('string(.)').get(default='').strip()
        title = response.xpath(title_xpath).xpath('string(.)').get(default=default_title).strip()
        if not title:
            warnings.append('no_title')
            title = self._slug_title(response.url)

        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body) if body else ''
        item['source_site'] = self.site_id
        item['source_type'] = self.source_type
        item['warnings'] = ','.join(warnings)
        yield item
