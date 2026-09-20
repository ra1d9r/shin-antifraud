"""Роуты REST API."""

from app.api.routes import (
    analytics,
    feedback,
    health,
    monitoring,
    predict,
    scenarios,
    stats,
    transactions,
)

__all__ = [
    "analytics",
    "feedback",
    "health",
    "monitoring",
    "predict",
    "scenarios",
    "stats",
    "transactions",
]
