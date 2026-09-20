"""Роуты REST API."""

from app.api.routes import (
    analytics,
    config,
    feedback,
    graph,
    health,
    monitoring,
    predict,
    report,
    scenarios,
    stats,
    transactions,
)

__all__ = [
    "analytics",
    "config",
    "feedback",
    "graph",
    "health",
    "monitoring",
    "predict",
    "report",
    "scenarios",
    "stats",
    "transactions",
]
