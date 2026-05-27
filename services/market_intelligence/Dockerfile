FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/market_intelligence/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r ./requirements.txt

COPY services/ ./services/
COPY data/ ./data/
COPY scraping/data/output/ ./scraping/data/output/

EXPOSE 8001

CMD ["uvicorn", "services.market_intelligence.main:app", "--host", "0.0.0.0", "--port", "8001"]
