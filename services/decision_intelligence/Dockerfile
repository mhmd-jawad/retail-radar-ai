FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY services/decision_intelligence/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy service code
COPY services/ ./services/
COPY stylepulse/ ./stylepulse/
COPY data/real/ ./data/real/

# Create output directories
RUN mkdir -p services/decision_intelligence/data/features \
             services/decision_intelligence/models/catboost_decision

EXPOSE 8002

CMD ["uvicorn", "services.decision_intelligence.main:app", \
     "--host", "0.0.0.0", "--port", "8002"]
