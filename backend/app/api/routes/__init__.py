"""Роуты REST API."""

from app.api.routes import (
    analytics,
    config,
    feature_list,
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
    "feature_list",
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
