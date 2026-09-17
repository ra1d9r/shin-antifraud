"""Доменные исключения Shin.

Отделены от HTTP: сервисы и ML-слой бросают эти ошибки, а API-слой
переводит их в корректные HTTP-коды (см. `app/main.py`).
"""

from __future__ import annotations


class ShinError(Exception):
    """Базовая ошибка системы."""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class ModelNotLoadedError(ShinError):
    """Модель не обучена или файл артефакта отсутствует."""

    status_code = 503
    error_code = "model_not_loaded"


class ModelLoadError(ShinError):
    """Артефакт модели есть, но не читается (битый файл, несовместимая версия)."""

    status_code = 503
    error_code = "model_load_failed"


class FeatureBuildError(ShinError):
    """Не удалось построить признаки для транзакции."""

    status_code = 422
    error_code = "feature_build_failed"


class ExplanationError(ShinError):
    """Сбой XAI-модуля при объяснении решения."""

    status_code = 500
    error_code = "explanation_failed"


class InvalidConfigurationError(ShinError):
    """Некорректная конфигурация (например, пороги риска не возрастают)."""

    status_code = 400
    error_code = "invalid_configuration"


class DatasetNotFoundError(ShinError):
    """Датасет для обучения не найден."""

    status_code = 404
    error_code = "dataset_not_found"
