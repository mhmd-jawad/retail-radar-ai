Feature Engineering
===================

The feature engineering sub-package transforms raw inventory and competitor
data into the columns expected by the CatBoost model. The training-time and
runtime paths are kept in sync so online predictions match offline training.

.. toctree::
   :maxdepth: 2

   engineer
   runtime_features
   validate
   clean_competitors
