"""Модуль сбора отзывов Google."""

__all__ = ["ReviewsService"]


def __getattr__(name: str):
    if name == "ReviewsService":
        from modules.reviews.service import ReviewsService

        return ReviewsService
    raise AttributeError(name)
