Rules Engine
============

The rules engine runs **6 hard business rules** before the ML model. Rules
protect the business from decisions no model should ever make — they cannot be
turned off without a code change.

.. note::
   An ``"absolute"`` override strength causes ``run_rules()`` to short-circuit
   and the ML model output is ignored entirely. A ``"strong"`` rule forces an
   action but does not stop other rules from accumulating nudges. A ``"soft"``
   rule adds a nudge signal without forcing anything.

.. toctree::
   :maxdepth: 2

   engine

