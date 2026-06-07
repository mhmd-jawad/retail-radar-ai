FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APIFY_SHARED_SRC=/home/myuser/shared_src \
    STORE_NAME=kix

WORKDIR /home/myuser

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/requirements.txt

COPY shared_src /home/myuser/shared_src
COPY src /home/myuser/src

CMD ["python", "-m", "src"]
