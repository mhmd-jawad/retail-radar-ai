# Retail Radar - KIX Lebanon Scraper

This Apify Actor wraps the existing Retail Radar scraper for `kix`.

## Source store

- Base URL: `https://kixlb.com`

## Output

The Actor writes normalized product records to:

- the default dataset
- `OUTPUT_SUMMARY` in the default key-value store
- `OUTPUT_JSON` in the default key-value store
- `OUTPUT_CSV` in the default key-value store

## Local test

1. Create a virtual environment.
2. Install `requirements.txt`.
3. Run `python -m src` from this actor folder.

## Cloud deployment

1. Run `apify login`.
2. Run `apify push` from this actor folder.
3. Start the Actor in Apify Console with the generated input UI.
