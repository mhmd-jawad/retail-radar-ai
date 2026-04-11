# StylePulse AI Scraping

This is the multi-brand competitor scraping area. It is separate from the old Adidas-only prototype and normalizes each retailer into one daily product snapshot schema.

## Target Shops

- `adidas_lb` - adidas Lebanon, sitemap + product-page JSON-LD
- `mikesport` - MikeSport Lebanon, Shopify `products.json`
- `tchooz` - Tchooz Shoes, Shopify `products.json`
- `shoesworld` - ShoesWorld Lebanon, Next/Vercel JSON API
- `citysport` - CitySport, Next/Vercel JSON API
- `kix` - KIX Lebanon, Shopify `products.json`
- `marka_store` - Marka Store Lebanon, Shopify `products.json`

## Output Schema

Every adapter writes:

```text
competitor_product_id
competitor_name
style_code
brand_name
product_name
category
gender_target
competitor_price
competitor_sale_price
discount_pct
is_on_sale
availability
currency
sizes_available
source_url
scraped_at
data_valid
```

`style_code` is optional because it is only available when the shop exposes a model/article code. A row can still be `data_valid=true` without `style_code`; those rows can feed Level 2 description matching and Level 3 category pressure later.

## Run A Small Test

From the repo root:

```bash
python -m scraping.cli --shops all --sample-size 2
```

This writes per-shop and combined outputs under:

```text
scraping/data/outputs/
```

To create one stable version per shop without deleting the timestamped history:

```bash
python -m scraping.organize_outputs
```

That writes:

```text
scraping/data/output/
  manifest.json
  combined/
  adidas_lb/
  mikesport/
  tchooz/
  shoesworld/
  citysport/
  kix/
  marka_store/
```

## Run One Shop

```bash
python -m scraping.cli --shops mikesport --sample-size 5
```

## Full Catalog Mode

Use this only after validating the sample outputs:

```bash
python -m scraping.cli --shops all --full
```

You can cap adapters during debugging:

```bash
python -m scraping.cli --shops adidas_lb --full --max-pages 1
```

## Matching Plan For The Next Step

The scraper only collects normalized competitor snapshots. The matching layer should run after storage:

1. Level 1 exact match: same brand plus same `style_code`.
2. Level 2 description match: normalized title, brand, category, gender, color/sport tokens, and price band.
3. Level 3 category match: same brand/category/segment/price band for category sale pressure, not one-to-one markdown math.
