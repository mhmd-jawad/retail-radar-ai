"""Sphinx configuration for StylePulse AI / Retail Radar AI documentation."""

import os
import sys
from unittest.mock import MagicMock

# -- Path setup ---------------------------------------------------------------
# Allow autodoc to import project packages without an editable install.
sys.path.insert(0, os.path.abspath("../../.."))

# Mock heavy dependencies unavailable in the docs build environment.
MOCK_MODULES = [
    "catboost",
    "mlflow",
    "mlflow.tracking",
    "mlflow.models",
    "psycopg",
    "psycopg.errors",
    "psycopg.rows",
    "prometheus_client",
    "prometheus_fastapi_instrumentator",
    "anthropic",
    "openai",
    "shap",
    "pandera",
    "pandera.typing",
    "replicate",
    "httpx",
    "telegram",
    "telegram.ext",
    "pandas",
    "numpy",
    "sklearn",
    "sklearn.preprocessing",
    "sklearn.metrics",
    "sklearn.model_selection",
    "fastapi",
    "fastapi.middleware",
    "fastapi.middleware.cors",
    "fastapi.responses",
    "fastapi.staticfiles",
    "fastapi.security",
    "pydantic",
    "pydantic.fields",
    "uvicorn",
    "aiofiles",
    "PIL",
    "PIL.Image",
]
for _mod in MOCK_MODULES:
    sys.modules.setdefault(_mod, MagicMock())

# -- Project information ------------------------------------------------------
project = "StylePulse AI"
copyright = "2026, Hassan Aboali and contributors"
author = "Hassan Aboali"
release = "1.0.0"

# -- General configuration ----------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autosectionlabel",
    "sphinx_copybutton",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- autodoc ------------------------------------------------------------------
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "private-members": False,
    "special-members": "__init__",
    "show-inheritance": True,
    "member-order": "bysource",
}
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"
autodoc_preserve_defaults = True
add_module_names = False

# -- napoleon -----------------------------------------------------------------
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_rtype = True
napoleon_preprocess_types = True

# -- intersphinx --------------------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3.11", None),
}

# -- autosectionlabel ---------------------------------------------------------
autosectionlabel_prefix_document = True

# -- HTML output --------------------------------------------------------------
html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_title = "StylePulse AI Documentation"

html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
    "light_css_variables": {
        "color-brand-primary": "#2563eb",
        "color-brand-content": "#2563eb",
    },
    "dark_css_variables": {
        "color-brand-primary": "#60a5fa",
        "color-brand-content": "#60a5fa",
    },
    "footer_icons": [],
}
