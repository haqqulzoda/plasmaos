"""
Plasma AI — Domain-Specific Repository Exceptions

Custom exception hierarchy for the CRUD / repository layer.
These exceptions are NOT HTTP exceptions — they are domain errors
that callers (API endpoints, Celery workers) translate into the
appropriate transport-level response.
"""

from __future__ import annotations

from uuid import UUID


class PlasmaRepositoryError(Exception):
    """Base exception for all repository-layer errors."""


class ProfileNotFoundException(PlasmaRepositoryError):
    """
    Raised when a CompanyProfile does not exist for the given user.

    This is a hard failure — compliance matching cannot proceed without
    a profile, so callers must handle this explicitly.
    """

    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id
        super().__init__(
            f"CompanyProfile not found for user_id={user_id}. "
            "Compliance matching cannot proceed without a hydrated profile."
        )
