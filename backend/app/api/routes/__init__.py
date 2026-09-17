"""Роуты REST API."""

from app.api.routes import health, predict, scenarios, stats, transactions

__all__ = ["health", "predict", "scenarios", "stats", "transactions"]
