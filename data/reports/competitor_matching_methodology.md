# Competitor Matching Methodology

## Purpose

StylePulse AI recommends whether a product should be **HOLD**, **MARKDOWN**, **PROMOTE**, or **CLEAR**. To make that decision, the model needs competitor price signals when reliable competitor evidence exists.

In real retail data, the same product is not always listed by competitors with the exact same SKU or style code. The matching mechanism solves this by using layered matching:

1. Try to find the exact same product.
2. If exact matching fails, search for a highly similar product.
3. If similarity is not strong enough, treat the product as having no reliable competitor match.

This prevents weak competitor comparisons from misleading the pricing model.

## Matching Layers

### 1. Exact Style Match

The strongest match is an exact normalized product key:

```text
BRAND|STYLE_CODE
```

Example:

```text
ADIDAS|B75807
```

If this key exists in the competitor dataset, the system uses those competitor rows directly.

Match type:

```text
exact_style
```

Match score:

```text
1.00
```

### 2. Same Model Family Fallback

If exact style matching fails, the system checks for products with:

- Same normalized brand
- Same normalized category
- Same normalized gender target
- Strong product-name token overlap
- Reasonable price similarity

This is used when the competitor product is effectively the same product family, even if the SKU or style code is missing.

Match type:

```text
same_model_family
```

### 3. Similar Product Fallback

If the product is not clearly the same model family, the system can still accept a close substitute when:

- Brand/category/gender still match
- Product names overlap enough
- Price is in a comparable band

Match type:

```text
similar_product
```

This is weaker than `same_model_family`, but still useful when exact competitor inventory is unavailable.

## Threshold Rule

Fallback matches are accepted only when:

```text
match_score > 0.60
```

Important:

- `0.60` is rejected.
- Anything below or equal to `0.60` is treated as **no reliable competitor found**.
- This keeps the model conservative and avoids using weak market evidence.

When no reliable competitor is found, the competitor fields sent to the model are neutral:

```text
num_competitors_tracked = 0
price_gap_pct = 0.0
competitors_on_sale_count = 0
competitors_out_of_stock_count = 0
```

The recommendation then depends on internal business signals such as inventory, margin, product age, seasonality, and cash pressure.

## Current Dataset Coverage

Current retailer catalog:

```text
400 products
```

Reliable competitor coverage:

```text
330 products matched
70 products with no reliable competitor match
```

Breakdown:

```text
323 exact_style matches
6 same_model_family fallback matches
1 similar_product fallback match
```

## Fallback Match Examples

| SKU | Product | Match Type | Score | Competitor | Competitor Price |
|---|---|---:|---:|---|---:|
| SP-9358D6C153 | FEED YOUR PUMA Backpack PRIME Kids | same_model_family | 0.9800 | tchooz | 60.00 |
| SP-176380B593 | FEED YOUR PUMA Backpack PRIME Girls | same_model_family | 0.9619 | tchooz | 60.00 |
| SP-7EBCBD2E4F | CATS CLUB Tee PS Boys | same_model_family | 0.9755 | tchooz | 10.00 |
| SP-7DFB8328BE | New Balance Fresh Foam X Trail More v3 Black/Pink/Yellow Women's Trail Shoes | same_model_family | 0.9800 | shoesworld | 85.00 |
| SP-2A3C5C0C82 | The North Face Glenclyffe Urban Boots in a white dune/tnf black colorway | same_model_family | 0.8787 | mikesport | 80.00 |
| SP-3350E7D69E | ADIDAS COPA PURE II+ FG BOOTS39+45 | similar_product | 0.7799 | adidas_lb | 79.00 |

## Runtime Prediction Flow

When a user selects a product and asks for a prediction:

1. The system loads the selected product data.
2. It loads the latest competitor scrape dataset.
3. It tries exact style matching first.
4. If exact matching fails, it tries fallback matching.
5. If a reliable match is found, competitor price features are sent to IE2.
6. If no reliable match is found, neutral competitor features are sent to IE2.
7. IE2 predicts using the existing CatBoost model and unchanged feature contract.

The matching metadata is stored for reporting and audit, but it is not added as a model feature. This means no model retraining is required for this version.

## Why This Matters

This approach makes the recommendation engine more realistic:

- It uses exact competitor prices when available.
- It still benefits from strong substitute products when exact SKU matching fails.
- It avoids making pricing decisions from weak or unrelated competitor matches.
- It keeps the model stable because the trained CatBoost feature list does not change.

