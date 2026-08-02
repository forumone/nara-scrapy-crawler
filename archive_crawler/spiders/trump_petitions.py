import scrapy

from archive_crawler.spiders.base import PetitionsSpiderMixin


class TrumpPetitionsSpider(PetitionsSpiderMixin, scrapy.Spider):
    name = "trump_petitions"
    allowed_domains = ["petitions.trumpwhitehouse.archives.gov"]

    SOURCE_SITE = 'petitions.trumpwhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'
