"""
Converts a KPI deviation into an OpsSeverity band.

Formula: distance_pct × base_weight × (1 + learned_adjustment) → band

Bands:
  0–25%  → LOW
  25–60% → MEDIUM
  60–100% → HIGH
  100%+  → CRITICAL
"""

from app.models.operational_alert import OpsSeverity, ThresholdDirection


def compute_severity(
    direction: ThresholdDirection,
    threshold_value: float,
    actual_value: float,
    base_weight: float = 1.0,
    learned_adjustment: float | None = None,
) -> OpsSeverity:
    if threshold_value == 0:
        return OpsSeverity.HIGH

    if direction == ThresholdDirection.LOWER_IS_BETTER:
        # Exceeded threshold — higher is worse
        if actual_value <= threshold_value:
            return OpsSeverity.LOW
        distance_pct = (actual_value - threshold_value) / threshold_value
    elif direction == ThresholdDirection.HIGHER_IS_BETTER:
        # Below threshold — lower is worse
        if actual_value >= threshold_value:
            return OpsSeverity.LOW
        distance_pct = (threshold_value - actual_value) / threshold_value
    else:
        # TARGET_BAND: treat threshold as the upper edge; above = issue
        if actual_value <= threshold_value:
            return OpsSeverity.LOW
        distance_pct = (actual_value - threshold_value) / threshold_value

    adjustment = 1 + (learned_adjustment or 0)
    score = distance_pct * base_weight * adjustment

    if score >= 1.0:
        return OpsSeverity.CRITICAL
    if score >= 0.6:
        return OpsSeverity.HIGH
    if score >= 0.25:
        return OpsSeverity.MEDIUM
    return OpsSeverity.LOW
