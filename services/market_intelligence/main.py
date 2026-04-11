"""
IE1 — Market Intelligence Service.
Owner: Mohammad Jawad.

Status: STUB — endpoints defined but not implemented.
IE1 collects competitor pricing from scraping/*.py and exposes it to IE2.

Contract:
  The output of each endpoint must conform to CompetitorSignals (imported
  from services.decision_intelligence.schemas).

Port: 8001
Run:
    uvicorn services.market_intelligence.main:app --port 8001 --reload
"""

from fastapi import FastAPI
from pydantic import BaseModel

# IE1 must produce data that conforms to IE2's CompetitorSignals schema
from services.decision_intelligence.schemas import CompetitorSignals

app = FastAPI(
    title="StylePulse AI — IE1 Market Intelligence",
    description="Competitor pricing signals service",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {"status": "healthy", "service": "ie1_market_intelligence"}


@app.get("/competitor/{sku_id}", response_model=CompetitorSignals)
def get_competitor_signals(sku_id: str):
    """
    TODO (Mohammad Jawad): Return scraped competitor pricing for a SKU.
    Reads from scraping/data/output/, aggregates per product,
    returns CompetitorSignals conforming to IE2 schema.
    """
    raise NotImplementedError("IE1: get_competitor_signals not implemented yet")


@app.post("/ingest/competitor")
def ingest_competitor(signals: CompetitorSignals):
    """
    TODO (Mohammad Jawad): Accept scraped competitor data and persist it.
    Called by the scraper runner after each shop scrape.
    """
    raise NotImplementedError("IE1: ingest_competitor not implemented yet")
