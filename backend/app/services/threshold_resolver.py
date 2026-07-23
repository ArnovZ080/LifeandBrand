"""
Threshold resolution — walks up the OrgUnit tree until a ThresholdConfig is found.

Conflict rule: a child org unit may NOT set a threshold that is laxer than its
nearest ancestor's threshold. Laxness is determined by ThresholdDirection:
  LOWER_IS_BETTER → child value must be <= ancestor value
  HIGHER_IS_BETTER → child value must be >= ancestor value
  TARGET_BAND → child value must be <= ancestor value (tighter band)

Raises ThresholdConflict (a plain ValueError with structured data) when violated.
"""

from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.operational_alert import ThresholdConfig, ThresholdDirection


@dataclass
class ThresholdConflict(Exception):
    kpi_type: str
    proposed_value: float
    ancestor_value: float
    ancestor_org_unit_id: int

    def __str__(self) -> str:
        return (
            f"Threshold for '{self.kpi_type}' ({self.proposed_value}) is laxer than "
            f"the ancestor threshold ({self.ancestor_value}) at org_unit {self.ancestor_org_unit_id}."
        )


def _ancestor_ids(db: Session, org_unit_id: int) -> list[int]:
    result = db.execute(
        text("""
            WITH RECURSIVE ancestors AS (
                SELECT parent_id FROM org_units WHERE id = :id AND parent_id IS NOT NULL
                UNION ALL
                SELECT o.parent_id FROM org_units o
                INNER JOIN ancestors a ON o.id = a.parent_id
                WHERE o.parent_id IS NOT NULL
            )
            SELECT parent_id FROM ancestors
        """),
        {"id": org_unit_id},
    )
    return [row[0] for row in result]


def get_effective_threshold(
    db: Session,
    kpi_type: str,
    org_unit_id: int,
) -> ThresholdConfig | None:
    """
    Returns the nearest ThresholdConfig for this kpi_type, checking this unit
    first, then walking up the hierarchy.
    """
    from sqlalchemy import text as sa_text
    ancestor_chain = [org_unit_id] + _ancestor_ids(db, org_unit_id)
    for unit_id in ancestor_chain:
        cfg = (
            db.query(ThresholdConfig)
            .filter(
                ThresholdConfig.kpi_type == kpi_type,
                ThresholdConfig.org_unit_id == unit_id,
            )
            .first()
        )
        if cfg:
            return cfg
    return None


def set_threshold(
    db: Session,
    kpi_type: str,
    org_unit_id: int,
    value: float,
    direction: ThresholdDirection,
    user_id: int | None = None,
) -> ThresholdConfig:
    """
    Creates or updates a ThresholdConfig, enforcing the conflict rule.
    Raises ThresholdConflict if the proposed value is laxer than an ancestor's.
    """
    # Find nearest ancestor threshold (excluding this unit itself)
    ancestor_ids = _ancestor_ids(db, org_unit_id)
    for anc_id in ancestor_ids:
        anc_cfg = (
            db.query(ThresholdConfig)
            .filter(ThresholdConfig.kpi_type == kpi_type, ThresholdConfig.org_unit_id == anc_id)
            .first()
        )
        if not anc_cfg:
            continue
        # Conflict check
        is_laxer = False
        if direction == ThresholdDirection.LOWER_IS_BETTER and value > anc_cfg.value:
            is_laxer = True
        elif direction == ThresholdDirection.HIGHER_IS_BETTER and value < anc_cfg.value:
            is_laxer = True
        elif direction == ThresholdDirection.TARGET_BAND and value > anc_cfg.value:
            is_laxer = True
        if is_laxer:
            raise ThresholdConflict(
                kpi_type=kpi_type,
                proposed_value=value,
                ancestor_value=float(anc_cfg.value),
                ancestor_org_unit_id=anc_id,
            )
        break  # Only check nearest ancestor

    # Upsert
    existing = (
        db.query(ThresholdConfig)
        .filter(ThresholdConfig.kpi_type == kpi_type, ThresholdConfig.org_unit_id == org_unit_id)
        .first()
    )
    if existing:
        existing.value = value
        existing.direction = direction
        existing.set_by_user_id = user_id
        db.commit()
        db.refresh(existing)
        return existing

    cfg = ThresholdConfig(
        kpi_type=kpi_type,
        org_unit_id=org_unit_id,
        value=value,
        direction=direction,
        set_by_user_id=user_id,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg
