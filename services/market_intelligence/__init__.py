"""
IE1 — Market Intelligence Service stub.
Implementation owner: Mohammad Jawad.

This package re-exports the CompetitorSignals schema (defined in IE2's
schemas.py) as the contract that IE1 must fulfil when posting data to IE2.

IE1 should POST /ingest/competitor to this service, which persists scraped
competitor prices and makes them available to IE2 via GET /competitor/{sku_id}.

Port: 8001
"""
