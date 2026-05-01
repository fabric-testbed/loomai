"""Jinja2 template configuration."""

from __future__ import annotations

import os

from fastapi.templating import Jinja2Templates

_template_dir = os.path.dirname(__file__)
templates = Jinja2Templates(directory=_template_dir)
