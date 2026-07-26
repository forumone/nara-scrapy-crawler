import csv
import json

import scrapy

from archive_crawler import exclusion_rules
from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class ObamaWhiteHouseSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "obama_whitehouse"
    allowed_domains = ["obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'www.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    @staticmethod
    def _extract_gallery_captions(response):
        """Extract every slideshow caption from a /photos-and-video/
        photogallery/* page.

        The slideshow itself is JS-driven and only ever renders the current
        slide's caption into the visible DOM (#photo-description) - a
        markup-based selector would silently return just one caption instead
        of the gallery's full set. Every caption is also embedded as static
        data in the page's own jQuery.extend(Drupal.settings, {...}) blob
        (Drupal.settings.wh_photog.descriptions), confirmed present and
        parseable on multiple unrelated galleries - no JS execution needed.
        """
        marker = 'jQuery.extend(Drupal.settings,'
        start = response.text.find(marker)
        if start == -1:
            return ''
        brace_start = response.text.find('{', start)
        if brace_start == -1:
            return ''
        try:
            settings, _ = json.JSONDecoder().raw_decode(response.text, brace_start)
        except json.JSONDecodeError:
            return ''
        descriptions = settings.get('wh_photog', {}).get('descriptions') or []
        return ' '.join(d.strip() for d in descriptions if d and d.strip())

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError("url_file argument is required: -a url_file=data/www.obamawhitehouse/www.obamawhitehouse_harvest-full.csv")
        rules = self._get_exclusion_rules()
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                url = row['url']
                reason = exclusion_rules.match_exclude(url, rules)
                if reason:
                    self._log_exclusion(url, reason)
                else:
                    yield self._make_request(url)

    def parse_item(self, response):
        if self._is_excluded_response(response):
            return
        body = (self._extract_text(response, '.field-items .field-item') or
                self._extract_text(response, '.longpage-sections') or
                self._extract_text(response, '#content') or
                self._extract_text(response, '#video-info .caption') or
                self._extract_gallery_captions(response))
        if not body:
            self._log_exclusion(response.url, 'no_body')
            return
        title = self._extract_title(response)
        if not title:
            self._log_exclusion(response.url, 'no_title')
            return
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item
