import csv
import re

import scrapy

from archive_crawler import exclusion_rules
from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin, PRESS_RELEASE_LETTERHEAD_PATTERNS


class GeorgeWBushWhiteHouseSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "georgewbush_whitehouse"
    allowed_domains = ["georgewbush-whitehouse.archives.gov"]

    SOURCE_SITE = 'www.georgewbush-whitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    # /911/ pages use <center><img src="/911/images/star.gif"></center> as a
    # decorative separator between nav links (including the literal text
    # "<before" and "next>" from prev/next anchors). Stripping the center
    # element that contains the gif removes the whole nav block.
    EXTRA_STRIP_XPATH = ('.//center[.//img[@src="/911/images/star.gif"]]',)

    LEADING_TEXT_STRIP_PATTERNS = PRESS_RELEASE_LETTERHEAD_PATTERNS

    # "White House News" is a breadcrumb/section label this template inserts
    # between the headline and the body text on ~6% of pages. Confirmed via
    # sampling it never appears as part of real content, always as this
    # exact standalone label.
    MIDTEXT_STRIP_PATTERNS = (
        re.compile(r'\s*White House News\s*'),
    )

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/www.georgewbush-whitehouse/georgewbush-whitehouse_harvest-full.csv"
            )
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
        # Selector chain across distinct sub-site layouts on this archive:
        # 1. #news_container — main WH press release layout (inside #whitebox).
        # 2. #whitebox — speeches/remarks on a slightly different WH template.
        # 3. #mainContent — OMB E-Gov sub-site (/omb/) with its own layout.
        # 4. font.BDYpixel — results.gov biographical content (/results/, /v/);
        #    old font-tag layout with no semantic container IDs.
        # 5. #main-content — OMB standard sub-sites (legislative SAPs, OIRA, circulars,
        #    pubpress, budget, etc.) and /kids/ educational content pages.
        # 6. #main-content2col — /kids/ two-column article pages (e.g. ABCs section).
        # 7. table#header-table ~ div — OMB earmark transparency pages (/omb/kn20drgh/,
        #    /omb/kn20drgg/, /omb/earmarks-*/); no semantic content ID, content sits in
        #    the first div sibling after the header nav table.
        # 8. .popupBodyWrap01 — OMB ExpectMore.gov detail pages.
        # 9. .content01 — OMB ExpectMore.gov summary pages (different template).
        # 10. //td[a[@name="content"]] — First Lady news/releases pages; content is in the
        #     TD that contains the skip-nav anchor (CSS :has() not supported by cssselect).
        body = (
            self._extract_text(response, '#news_container')
            or self._extract_text(response, '#whitebox')
            or self._extract_text(response, '#mainContent')
            or self._extract_text(response, 'font.BDYpixel')
            or self._extract_text(response, '#main-content')
            or self._extract_text(response, '#main-content2col')
            or self._extract_text(response, 'table#header-table ~ div')
            or self._extract_text(response, '.popupBodyWrap01')
            or self._extract_text(response, '.content01')
            or self._extract_text(response, '//td[a[@name="content"]]')
        )
        if not body:
            self._log_exclusion(response.url, 'no_body')
            return
        # No h1 on most pages; <title> tag matches the bolded article heading.
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
