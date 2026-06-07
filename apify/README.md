# Apify deployment scaffold for the retail scrapers

This folder packages the working scraper logic from the repo into Apify-friendly Python Actors.

## Layout

- `actors/<shop>/` - one Actor folder per store
- `tools/run_and_sync.py` - starts a cloud Actor run and writes the results back into `scraping/data/output/<shop>/`

## Actor folders

- `actors/adidas_lb`
- `actors/mikesport`
- `actors/tchooz`
- `actors/shoesworld`
- `actors/citysport`
- `actors/kix`
- `actors/marka_store`

## Recommended workflow

1. Develop in VS Code from this repo.
2. Open one Actor folder, for example `apify/actors/mikesport`.
3. Install the Apify CLI.
4. Log in with `apify login`.
5. Push that actor with `apify push`.
6. Run it in Apify Console or with the API.
7. Pull the dataset back into this repo with `python apify/tools/run_and_sync.py ...`.

Each actor folder is self-contained, so you can run `apify push` directly inside that actor directory.
