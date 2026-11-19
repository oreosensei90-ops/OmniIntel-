"""Measured cross-source clock alignment; proposals remain unreviewed by default."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Sequence

from .database import connect, migrate
from .ids import uuid7
from .models import utc_now


class AlignmentError(ValueError):
    pass


def estimate_offset(
    signal_a: Sequence[float],
    signal_b: Sequence[float],
    *,
    sample_interval_ms: int,
    max_lag_samples: int,
) -> dict[str, float | int]:
    """Estimate a coarse offset using normalized cross-correlation.

    Convention: time_in_A_ms = time_in_B_ms + offset_ms. Inputs must be
    precomputed feature envelopes on a shared nominal sampling interval.
    """
    if sample_interval_ms <= 0 or max_lag_samples < 0:
        raise AlignmentError("Sampling interval must be positive and max lag non-negative")
    if len(signal_a) < 8 or len(signal_b) < 8:
        raise AlignmentError("At least eight samples per signal are required")
    if max_lag_samples >= min(len(signal_a), len(signal_b)) - 3:
        raise AlignmentError("Maximum lag leaves too few overlapping samples")
    a = [float(x) for x in signal_a]
    b = [float(x) for x in signal_b]
    if not all(math.isfinite(x) for x in a + b):
        raise AlignmentError("Signals must contain only finite values")

    def corr(lag: int) -> float | None:
        # Positive lag pairs A[i] with B[i-lag].
        pairs = [(a[i], b[i-lag]) for i in range(max(0, lag), min(len(a), len(b)+lag))]
        if len(pairs) < 8:
            return None
        mean_a = sum(x for x, _ in pairs) / len(pairs)
        mean_b = sum(y for _, y in pairs) / len(pairs)
        da = [x-mean_a for x, _ in pairs]
        db = [y-mean_b for _, y in pairs]
        denom = math.sqrt(sum(x*x for x in da) * sum(y*y for y in db))
        return sum(x*y for x, y in zip(da, db)) / denom if denom else None

    candidates = [(lag, value) for lag in range(-max_lag_samples, max_lag_samples+1)
                  if (value := corr(lag)) is not None]
    candidates.sort(key=lambda item: item[1], reverse=True)
    best_lag, best = candidates[0]
    runner_up = next((score for lag, score in candidates[1:] if abs(lag-best_lag) > 1), -1.0)
    return {
        "offset_ms": best_lag * sample_interval_ms,
        "correlation": best,
        "runner_up_correlation": runner_up,
        "sample_interval_ms": sample_interval_ms,
        "max_lag_samples": max_lag_samples,
    }


class AlignmentStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)

    def propose(
        self, collection_id: str, source_a_id: str, source_b_id: str,
        estimate: dict[str, float | int], *, rationale: str,
        signal_a: Sequence[float], signal_b: Sequence[float],
    ) -> str:
        if source_a_id == source_b_id or not rationale.strip():
            raise AlignmentError("Two distinct sources and a rationale are required")
        offset = int(estimate["offset_ms"])
        interval = int(estimate["sample_interval_ms"])
        max_lag = int(estimate["max_lag_samples"])
        measured = estimate_offset(signal_a, signal_b, sample_interval_ms=interval, max_lag_samples=max_lag)
        if any(measured[key] != estimate[key] for key in ("offset_ms","correlation","runner_up_correlation")):
            raise AlignmentError("Estimate does not match the supplied feature envelopes")
        corr = float(estimate["correlation"])
        runner = float(estimate["runner_up_correlation"])
        if interval <= 0 or not -1 <= corr <= 1 or not -1 <= runner <= 1:
            raise AlignmentError("Invalid correlation estimate")
        if len(signal_a) < 8 or len(signal_b) < 8 or not all(
            math.isfinite(float(value)) for value in list(signal_a) + list(signal_b)
        ):
            raise AlignmentError("Alignment signals must contain at least eight finite samples each")
        payload = {"a": list(signal_a), "b": list(signal_b), "estimate": estimate}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
        alignment_id = uuid7()
        with connect(self.database_path) as conn:
            migrate(conn)
            conn.execute(
                """INSERT INTO source_clock_alignments
                   (id,collection_id,source_a_id,source_b_id,offset_ms,sample_interval_ms,
                    correlation,runner_up_correlation,method,algorithm_version,input_hash,
                    rationale,review_state,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'NEEDS_REVIEW',?)""",
                (alignment_id,collection_id,source_a_id,source_b_id,offset,interval,corr,runner,
                 "NORMALIZED_CROSS_CORRELATION","1",digest,rationale.strip(),utc_now()),
            )
        return alignment_id

    def review(self, alignment_id: str, state: str) -> str:
        if state not in {"ACCEPTED", "REJECTED", "NEEDS_REVIEW"}:
            raise AlignmentError("Unsupported alignment review state")
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """UPDATE source_clock_alignments SET review_state=?,reviewed_at=?
                   WHERE id=?""",
                (state,utc_now(),alignment_id),
            )
            if cursor.rowcount != 1:
                raise AlignmentError("Alignment candidate does not exist")
        return state

    def list(self, collection_id: str) -> list[dict[str, object]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                """SELECT * FROM source_clock_alignments
                   WHERE collection_id=? ORDER BY created_at,id""",(collection_id,)
            ).fetchall()
        return [dict(row) for row in rows]
