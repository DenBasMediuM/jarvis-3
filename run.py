#!/usr/bin/env python3
"""Run Jarvis locally: python run.py"""

from __future__ import annotations

import uvicorn

from core.config import settings


if __name__ == "__main__":
    uvicorn.run(
        "core.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
