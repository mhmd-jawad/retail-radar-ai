"""MikeSport Lebanon — Shopify store."""
from ..shopify_scraper import ShopifyScraper


class MikeSportLB(ShopifyScraper):
    retailer_name = "mikesport_lb"
    competitor_name = "MikeSport Lebanon"
    base_url = "https://lb.mikesport.com"
    currency = "USD"
