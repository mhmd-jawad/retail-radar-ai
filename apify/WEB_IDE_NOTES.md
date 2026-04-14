# Web IDE Manual Paste Notes

Use this only if you want to build each Actor directly inside Apify Console instead of pushing from VS Code.

## Recommended manual file tree per Actor

Create these paths inside the Actor root in Apify Web IDE:

- `.actor/actor.json`
- `.actor/INPUT_SCHEMA.json`
- `Dockerfile`
- `README.md`
- `requirements.txt`
- `src/__main__.py`
- `src/main.py`
- `shared_src/scraping/__init__.py`
- `shared_src/scraping/common/...`
- `shared_src/scraping/shops/...`

For the shared package, copy the contents from the matching actor's `shared_src/scraping` folder, for example [apify/actors/mikesport/shared_src/scraping](/C:/Users/Administrator/Desktop/project503n/retail-radar-ai/apify/actors/mikesport/shared_src/scraping).

For the actor-specific files, copy them from the matching folder under [apify/actors](/C:/Users/Administrator/Desktop/project503n/retail-radar-ai/apify/actors).

## Two files that change for Web IDE

If you create the Actor manually in Web IDE, do not use the monorepo `dockerContextDir` setting from the local scaffold.

Use this `.actor/actor.json` pattern instead:

```json
{
  "actorSpecification": 1,
  "name": "retail-radar-mikesport-scraper",
  "title": "Retail Radar - MikeSport Lebanon Scraper",
  "version": "0.1",
  "buildTag": "latest",
  "dockerfile": "./Dockerfile",
  "readme": "./README.md",
  "input": "./INPUT_SCHEMA.json",
  "environmentVariables": {
    "STORE_NAME": "mikesport"
  }
}
```

Use this `Dockerfile` pattern instead:

```dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APIFY_SHARED_SRC=/home/myuser/shared_src \
    STORE_NAME=mikesport

WORKDIR /home/myuser

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/requirements.txt

COPY shared_src /home/myuser/shared_src
COPY src /home/myuser/src

CMD ["python", "-m", "src"]
```

Everything else can stay the same as the files already generated in this repo.
