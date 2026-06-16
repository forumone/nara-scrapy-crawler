from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.spiders.base import NavHarvesterMixin


class ObamaWhiteHouseHarvestNavSpider(NavHarvesterMixin, CrawlSpider):
    name = "obama_whitehouse_harvest_nav"
    allowed_domains = ["obamawhitehouse.archives.gov"]

    start_urls = [
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

    custom_settings = {
        'DEPTH_LIMIT': 2,
    }

    rules = (
        Rule(
            LinkExtractor(allow_domains=['obamawhitehouse.archives.gov']),
            callback='parse_nav',
            follow=True,
            process_links='_filter_web_urls',
        ),
    )
