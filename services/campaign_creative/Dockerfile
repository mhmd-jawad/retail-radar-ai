FROM python:3.11-slim

WORKDIR /app

# System fonts for Pillow image generation (Liberation Sans = Arial equivalent)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY services/campaign_creative/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy service code (needs decision_intelligence schemas as a dependency)
COPY services/ ./services/

# Ensure the static image directory exists
RUN mkdir -p services/campaign_creative/static

EXPOSE 8003

CMD ["uvicorn", "services.campaign_creative.main:app", \
     "--host", "0.0.0.0", "--port", "8003"]
