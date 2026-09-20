"""Роуты REST API."""

from app.api.routes import (
    analytics,
    feedback,
    health,
    predict,
    scenarios,
    stats,
    transactions,
)

__all__ = [
    "analytics",
    "feedback",
    "health",
    "predict",
    "scenarios",
    "stats",
    "transactions",
]
