"""Роуты REST API."""

from app.api.routes import (
    analytics,
    batch,
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
    "batch",
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
