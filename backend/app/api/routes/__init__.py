"""Роуты REST API."""

from app.api.routes import (
    analytics,
    feedback,
    graph,
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
    "graph",
    "health",
    "monitoring",
    "predict",
    "scenarios",
    "stats",
    "transactions",
]
