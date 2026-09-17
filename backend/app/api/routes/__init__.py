"""Роуты REST API."""

from app.api.routes import health, predict, stats, transactions

__all__ = ["health", "predict", "stats", "transactions"]
