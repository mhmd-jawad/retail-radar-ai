StylePulse Offline Engine
==========================

The StylePulse Engine is a standalone analysis pipeline that processes flat
CSV data and produces a JSON advisory report. It is not a live service — it
runs on demand or on a schedule.

Run it from the repo root::

   python -m stylepulse run --data-dir data/real --output-dir data/reports

.. toctree::
   :maxdepth: 2

   engine
   analyzers/index
   report/generator
