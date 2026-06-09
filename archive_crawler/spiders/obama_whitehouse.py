import csv

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin

# Content pages reachable only from site navigation, not from any listing page.
NAV_ONLY_URLS = [
    'https://obamawhitehouse.archives.gov/',
    'https://obamawhitehouse.archives.gov/briefing-room',
    'https://obamawhitehouse.archives.gov/briefing-room/disclosures',
    'https://obamawhitehouse.archives.gov/briefing-room/disclosures/visitor-records',
    'https://obamawhitehouse.archives.gov/briefing-room/disclosures/financial-disclosures',
    'https://obamawhitehouse.archives.gov/briefing-room/disclosures/ethics-pledge-waivers',
    'https://obamawhitehouse.archives.gov/the-record',
    'https://obamawhitehouse.archives.gov/issues',
    'https://obamawhitehouse.archives.gov/administration',
    'https://obamawhitehouse.archives.gov/administration/president-obama',
    'https://obamawhitehouse.archives.gov/vp',
    'https://obamawhitehouse.archives.gov/administration/first-lady-michelle-obama',
    'https://obamawhitehouse.archives.gov/administration/jill-biden',
    'https://obamawhitehouse.archives.gov/administration/cabinet',
    'https://obamawhitehouse.archives.gov/administration/cabinet/exit-memos',
    'https://obamawhitehouse.archives.gov/administration/eop',
    'https://obamawhitehouse.archives.gov/administration/senior-leadership',
    'https://obamawhitehouse.archives.gov/espanol',
    'https://obamawhitehouse.archives.gov/accessibility',
    'https://obamawhitehouse.archives.gov/joiningforces',
    'https://obamawhitehouse.archives.gov/reach-higher',
    'https://obamawhitehouse.archives.gov/my-brothers-keeper',
    'https://obamawhitehouse.archives.gov/precision-medicine',
    'https://obamawhitehouse.archives.gov/champions',
    'https://obamawhitehouse.archives.gov/climate-change',
    'https://obamawhitehouse.archives.gov/economy',
    'https://obamawhitehouse.archives.gov/education',
    'https://obamawhitehouse.archives.gov/trade',
    'https://obamawhitehouse.archives.gov/21stcenturygov',
    'https://obamawhitehouse.archives.gov/1600',
    'https://obamawhitehouse.archives.gov/1600/Presidents',
    'https://obamawhitehouse.archives.gov/1600/first-ladies',
    'https://obamawhitehouse.archives.gov/about/inside-white-house',
    'https://obamawhitehouse.archives.gov/sotu',
    'https://obamawhitehouse.archives.gov/farewell',
    'https://obamawhitehouse.archives.gov/medal-of-freedom',
    'https://obamawhitehouse.archives.gov/inauguration-2013',
    'https://obamawhitehouse.archives.gov/participate',
    'https://obamawhitehouse.archives.gov/omb',
    'https://obamawhitehouse.archives.gov/we-the-geeks',
]


class ObamaWhiteHouseSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "obama_whitehouse"
    allowed_domains = ["obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        seen = set()
        if url_file:
            with open(url_file, newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    url = row['url']
                    if url not in seen:
                        seen.add(url)
                        yield scrapy.Request(url, callback=self.parse_item)
        for url in NAV_ONLY_URLS:
            if url not in seen:
                seen.add(url)
                yield scrapy.Request(url, callback=self.parse_item)

    def parse_item(self, response):
        if response.css('.views-row'):
            return
        body = (self._extract_text(response, '.field-items .field-item') or
                self._extract_text(response, '.longpage-sections'))
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
