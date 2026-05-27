FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY services/decision_intelligence/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy service code
COPY services/ ./services/
COPY stylepulse/ ./stylepulse/
COPY data/real/ ./data/real/

EXPOSE 8002

CMD ["uvicorn", "services.decision_intelligence.main:app", \
     "--host", "0.0.0.0", "--port", "8002"]
