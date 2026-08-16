"""
Source adapter contract for the 5-stage ingest pipeline (Phase 0 Foundation).

Every external data source (Micros POS, Sage, Pilot, ...) implements
SourceAdapter. The pipeline service drives the stages:
discover → parse (landed payload) → normalise (canonical rows) → reconcile → serve.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PipelineResult:
    """Outcome of one pipeline stage for one file."""
    ingest_id: int | None
    source: str
    stage: str
    ok: bool
    rows: int
    message: str = ""


class SourceAdapter(ABC):
    """Contract every source connector must fulfil."""

    @abstractmethod
    def source_key(self) -> str:
        """Stable key identifying this source, e.g. 'micros'."""
        ...

    @abstractmethod
    def discover(self, watch_dir: str) -> list[str]:
        """Return paths of new files in watch_dir not yet ingested."""
        ...

    @abstractmethod
    def parse(self, path: str) -> dict:
        """Parse a raw file into a payload dict (stored verbatim on RawIngest)."""
        ...

    @abstractmethod
    def normalise(self, payload: dict) -> list[dict]:
        """Turn a raw payload into canonical rows.

        Each row carries: org_unit pos_site_code, business_date, gross_sales,
        vat, discounts, covers — plus item-level lines if present.
        """
        ...
