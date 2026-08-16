"""
5-stage ingest pipeline (Phase 1).

landed → staged → normalised → reconciled → served (or failed at any stage).

Each discovered file becomes one RawIngest row whose ``stage`` advances as it
passes each gate. Failures mark the row ``failed`` with an error message and
never abort the run for other files. The raw parse payload is kept verbatim;
the normalised rows are written back into ``payload["normalised"]`` so any
stage can be replayed.

Reconcile writes into the Sale table: the current Sale model stores a single
amount (``total_revenue``) per site per business date, which the platform
treats as L2 net sales (net of VAT and discounts). Item-level lines are
written as SaleLine rows when the POS item code (or name) matches a MenuItem;
unmatched lines are noted but not fatal.
"""
from __future__ import annotations

import traceback
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import PipelineResult, SourceAdapter
from app.connectors.micros_adapter import sha256_file
from app.models import MenuItem, OrgUnit, RawIngest, Sale, SaleLine
from app.models.raw_ingest import IngestStage

RECONCILE_TOLERANCE = Decimal("0.01")  # 1 cent


def known_hashes(db: Session) -> set[str]:
    return set(db.execute(select(RawIngest.file_hash)).scalars())


def run_pipeline(db: Session, adapter: SourceAdapter, watch_dir: str) -> list[PipelineResult]:
    """Run all 5 stages for every new file the adapter discovers."""
    results: list[PipelineResult] = []
    source = adapter.source_key()

    for path in adapter.discover(watch_dir):
        ingest: RawIngest | None = None
        try:
            # ── Stage 1: Land ─────────────────────────────────────────────────────
            file_hash = sha256_file(path)
            if db.execute(select(RawIngest.id).where(RawIngest.file_hash == file_hash)).first():
                results.append(PipelineResult(
                    ingest_id=None, source=source, stage="skipped", ok=True, rows=0,
                    message=f"{path}: duplicate file hash, already ingested"))
                continue

            payload = adapter.parse(path)
            ingest = RawIngest(
                source=source,
                file_name=payload.get("file_name") or path.rsplit("/", 1)[-1],
                file_hash=file_hash,
                stage=IngestStage.LANDED,
                payload=payload,
            )
            db.add(ingest)
            db.commit()
            db.refresh(ingest)

            # ── Stage 2: Stage (structural validation) ────────────────────────────────
            rows = payload.get("rows")
            if not isinstance(rows, list) or not rows:
                raise ValueError("Payload has no data rows")
            if not all(isinstance(r, dict) for r in rows):
                raise ValueError("Payload rows are not objects")
            ingest.stage = IngestStage.STAGED
            db.commit()

            # ── Stage 3: Normalise ──────────────────────────────────────────────────
            normalised = adapter.normalise(payload)
            if not normalised:
                raise ValueError(
                    "No rows could be normalised "
                    f"({len(payload.get('skipped_rows', []))} skipped)")

            site_codes = {r["pos_site_code"] for r in normalised}
            units = {
                u.pos_site_code: u
                for u in db.execute(
                    select(OrgUnit).where(OrgUnit.pos_site_code.in_(site_codes))
                ).scalars()
            }
            unknown = sorted(site_codes - set(units))
            if unknown:
                raise ValueError(f"Unknown pos_site_code(s): {', '.join(unknown)}")

            payload = dict(ingest.payload or payload)
            payload["normalised"] = normalised
            ingest.payload = payload
            ingest.row_count = len(normalised)
            # Single-site / single-date files get their identifiers stamped on
            if len(units) == 1:
                ingest.org_unit_id = next(iter(units.values())).id
            dates = {r["business_date"] for r in normalised}
            if len(dates) == 1:
                ingest.business_date = date.fromisoformat(next(iter(dates)))
            ingest.stage = IngestStage.NORMALISED
            db.commit()

            # ── Stage 4: Reconcile ──────────────────────────────────────────────────
            errors = _reconcile_checks(normalised)
            if errors:
                raise ValueError("Reconcile failed: " + "; ".join(errors))

            unmatched_lines = 0
            for row in normalised:
                unmatched_lines += _upsert_sale(db, units[row["pos_site_code"]], row)
            ingest.stage = IngestStage.RECONCILED
            db.commit()

            # ── Stage 5: Serve ──────────────────────────────────────────────────────
            ingest.stage = IngestStage.SERVED
            db.commit()

            msg = f"{ingest.file_name}: {len(normalised)} row(s) served"
            skipped = len(payload.get("skipped_rows") or [])
            if skipped:
                msg += f", {skipped} raw row(s) skipped"
            if unmatched_lines:
                msg += f", {unmatched_lines} item line(s) unmatched to menu items"
            results.append(PipelineResult(
                ingest_id=ingest.id, source=source, stage=IngestStage.SERVED.value,
                ok=True, rows=len(normalised), message=msg))

        except Exception as exc:  # noqa: BLE001 — any failure fails this file only
            db.rollback()
            message = f"{type(exc).__name__}: {exc}"
            if ingest is not None and ingest.id is not None:
                try:
                    ingest = db.get(RawIngest, ingest.id)
                    ingest.stage = IngestStage.FAILED
                    ingest.error = message + "\n" + traceback.format_exc(limit=5)
                    db.commit()
                except Exception:
                    db.rollback()
            results.append(PipelineResult(
                ingest_id=ingest.id if ingest is not None else None,
                source=source, stage=IngestStage.FAILED.value, ok=False, rows=0,
                message=f"{path}: {message}"))

    return results


def _reconcile_checks(normalised: list[dict]) -> list[str]:
    """Sanity checks: net = gross - vat - discounts (±1c), non-negative
    values, business date not in the future."""
    errors = []
    today = date.today()
    for row in normalised:
        ident = f"{row['pos_site_code']}/{row['business_date']}"
        gross, vat = row.get("gross_sales"), row.get("vat")
        discounts, net = row.get("discounts"), row.get("net_sales")
        if gross is not None and net is not None:
            expected = Decimal(str(gross)) - Decimal(str(vat or 0)) - Decimal(str(discounts or 0))
            if abs(expected - Decimal(str(net))) > RECONCILE_TOLERANCE:
                errors.append(f"{ident}: net {net} != gross - vat - discounts ({expected})")
        for field in ("gross_sales", "vat", "discounts", "net_sales", "covers"):
            value = row.get(field)
            if value is not None and value < 0:
                errors.append(f"{ident}: negative {field} ({value})")
        if date.fromisoformat(row["business_date"]) > today:
            errors.append(f"{ident}: business_date in the future")
    return errors


def _upsert_sale(db: Session, org_unit: OrgUnit, row: dict) -> int:
    """One Sale per site per business date; total_revenue holds L2 net sales.
    Existing rows (and their lines) are replaced. Returns the count of item
    lines that could not be matched to a MenuItem."""
    biz_date = date.fromisoformat(row["business_date"])
    sale = db.execute(
        select(Sale).where(Sale.location_id == org_unit.id, Sale.sale_date == biz_date)
    ).scalars().first()
    if sale is None:
        sale = Sale(location_id=org_unit.id, sale_date=biz_date)
        db.add(sale)
    sale.total_revenue = row.get("net_sales")
    sale.micros_batch_id = f"ingest:{row['pos_site_code']}:{row['business_date']}"
    db.flush()

    unmatched = 0
    lines = row.get("lines") or []
    if lines:
        sale.lines.clear()  # replace on re-ingest
        for line in lines:
            menu_item = None
            if line.get("pos_item_code"):
                menu_item = db.execute(
                    select(MenuItem).where(MenuItem.micros_item_id == str(line["pos_item_code"]))
                ).scalars().first()
            if menu_item is None and line.get("item_name"):
                menu_item = db.execute(
                    select(MenuItem).where(MenuItem.name == line["item_name"])
                ).scalars().first()
            if menu_item is None or line.get("qty") is None:
                unmatched += 1
                continue
            sale.lines.append(SaleLine(
                menu_item_id=menu_item.id,
                quantity_sold=line["qty"],
                revenue=line.get("gross_value"),
            ))
        db.flush()
    return unmatched
