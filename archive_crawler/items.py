# archive_crawler/items.py
import scrapy

class ArchiveItem(scrapy.Item):
    # These fields match your OpenSearch Mapping
    url = scrapy.Field()
    title = scrapy.Field()
    content = scrapy.Field()     # The main body text
    published_date = scrapy.Field()
    source_site = scrapy.Field() # Useful for filtering in search