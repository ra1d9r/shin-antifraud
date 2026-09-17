"""Explainable AI: вклады признаков и человекочитаемые причины."""

from app.xai.contributions import (
    AblationContributions,
    ContributionResult,
    LightGbmNativeContributions,
    ShapTreeContributions,
    build_contribution_engine,
    unwrap_tree_model,
)
from app.xai.explainer import Explainer, Explanation, RiskFactor

__all__ = [
    "AblationContributions",
    "ContributionResult",
    "Explainer",
    "Explanation",
    "LightGbmNativeContributions",
    "RiskFactor",
    "ShapTreeContributions",
    "build_contribution_engine",
    "unwrap_tree_model",
]
