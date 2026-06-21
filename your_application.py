"""Compatível com o Start Command padrão do Render: gunicorn your_application.wsgi"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from a2wsgi import ASGIMiddleware
from app.main import app

wsgi = ASGIMiddleware(app)
