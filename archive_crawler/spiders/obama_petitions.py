import scrapy

from archive_crawler.spiders.base import PetitionsSpiderMixin


class ObamaPetitionsSpider(PetitionsSpiderMixin, scrapy.Spider):
    name = "obama_petitions"
    allowed_domains = ["petitions.obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'petitions.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'
