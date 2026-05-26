FROM python:3.12-slim

ARG INSTALL_IE2=false

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY eep/requirements.txt /tmp/eep-requirements.txt
COPY services/decision_intelligence/requirements.txt /tmp/ie2-requirements.txt

RUN pip install --no-cache-dir -r /tmp/eep-requirements.txt \
    && if [ "$INSTALL_IE2" = "true" ]; then pip install --no-cache-dir -r /tmp/ie2-requirements.txt; fi

COPY eep ./eep
COPY infra ./infra
COPY data ./data
COPY scraping/data/output ./scraping/data/output
COPY stylepulse ./stylepulse
COPY services ./services

EXPOSE 8000

CMD ["uvicorn", "eep.main:app", "--host", "0.0.0.0", "--port", "8000"]
