"""Tender source connector package.

Keep this package initializer dependency-light: reproducibility helpers import
the key utilities in minimal test environments where SQLAlchemy may not be
installed.
"""

from app.services.tender_sources.keys import canonical_source_key, normalize_source_system

__all__ = [
    "canonical_source_key",
    "normalize_source_system",
]
