IE2 — Decision Intelligence
============================

IE2 is the ML heart of StylePulse AI. It runs **6 hard business rules** before
a CatBoost classifier, explains decisions using SHAP values, and exposes a
prediction endpoint consumed by EEP.

Runs on **port 8002** (owner: Hassan Fouani).

.. toctree::
   :maxdepth: 2

   main
   schemas
   calendar
   rules/index
   features/index
   explainability/index
   training/index
   evaluation/index
