StylePulse AI Documentation
============================

**StylePulse AI** is an AI-powered pricing and promotion intelligence platform
for Adidas single-brand retailers in Lebanon. It monitors competitor prices
daily, tracks inventory health, and recommends one of four decisions for every
SKU: **HOLD · MARKDOWN · PROMOTE · CLEAR** — with SHAP-based plain-English
explanations sent to the shop owner via Telegram.

.. rubric:: System Architecture

The platform is composed of four microservices that collaborate through the
EEP orchestrator:

- **EEP** (port 8000) — Request gateway, circuit breakers, approval workflow
- **IE1 Market Intelligence** (port 8001) — Live competitor price signals
- **IE2 Decision Intelligence** (port 8002) — CatBoost ML model + 6 hard rules
- **IE3 Campaign Creative** (port 8003) — Claude AI copy and image generation

An offline **StylePulse Engine** runs inventory, competitor, financial, and
promotion analyses against flat-file data to produce the initial advisory report.

.. toctree::
   :maxdepth: 2
   :caption: Overview

   architecture

.. toctree::
   :maxdepth: 3
   :caption: EEP — Orchestrator (port 8000)

   eep/index

.. toctree::
   :maxdepth: 3
   :caption: IE1 — Market Intelligence (port 8001)

   ie1/index

.. toctree::
   :maxdepth: 3
   :caption: IE2 — Decision Intelligence (port 8002)

   ie2/index

.. toctree::
   :maxdepth: 3
   :caption: IE3 — Campaign Creative (port 8003)

   ie3/index

.. toctree::
   :maxdepth: 3
   :caption: StylePulse Offline Engine

   stylepulse/index

.. toctree::
   :maxdepth: 3
   :caption: Data Pipeline

   data_pipeline/index

.. toctree::
   :maxdepth: 2
   :caption: Shared Utilities

   common/index

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
