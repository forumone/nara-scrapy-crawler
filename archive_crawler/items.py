# archive_crawler/items.py
import scrapy

class ArchiveItem(scrapy.Item):
    # These fields match your OpenSearch Mapping
    url = scrapy.Field()
    title = scrapy.Field()
    teaser_text = scrapy.Field()
    full_text = scrapy.Field()     # The main body text
    source_site = scrapy.Field()
    source_type = scrapy.Field()
    warnings = scrapy.Field()      # Comma-separated: no_body, short_body, no_title


class HarvestItem(scrapy.Item):
    url = scrapy.Field()
    is_listing = scrapy.Field()
    depth = scrapy.Field()