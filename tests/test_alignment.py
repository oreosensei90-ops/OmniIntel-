import sqlite3
from pathlib import Path

import pytest

from omniintel.alignment import AlignmentError, AlignmentStore, estimate_offset
from omniintel.collections import CollectionStore
from omniintel.store import OmniIntelStore


def source(db: Path, name: str) -> str:
    return OmniIntelStore(db).create_source(title=name)


def test_cross_correlation_estimates_offset_with_documented_sign() -> None:
    a=[0,1,0,0,2,0,0,1,0,0,3,0,0,1,0,0]
    b=[0,0,0,1,0,0,0,2,0,0,1,0,0,3,0,0]
    result=estimate_offset(a,b,sample_interval_ms=100,max_lag_samples=4)
    assert result["offset_ms"] == -300
    assert result["correlation"] > 0.90


def test_alignment_requires_review_and_collection_membership(tmp_path: Path) -> None:
    db=tmp_path/"db.sqlite"
    a,b=source(db,"A"),source(db,"B")
    collections=CollectionStore(db)
    course=collections.create("Course")
    collections.add_source(course,a)
    collections.add_source(course,b)
    signal=[0,1,0,2,0,1,0,2,0,1,0,2]
    estimate=estimate_offset(signal,signal,sample_interval_ms=100,max_lag_samples=2)
    store=AlignmentStore(db)
    record=store.propose(course,a,b,estimate,rationale="Shared audio envelope peak sequence",
                         signal_a=signal,signal_b=signal)
    assert store.list(course)[0]["review_state"]=="NEEDS_REVIEW"
    assert store.review(record,"ACCEPTED")=="ACCEPTED"
    other=source(db,"Not in course")
    with pytest.raises(sqlite3.IntegrityError,match="both aligned sources"):
        store.propose(course,a,other,estimate,rationale="Not a member",
                      signal_a=signal,signal_b=signal)


def test_alignment_rejects_short_or_invalid_signals() -> None:
    with pytest.raises(AlignmentError):
        estimate_offset([1,2],[1,2],sample_interval_ms=100,max_lag_samples=0)
    with pytest.raises(AlignmentError):
        estimate_offset([1,float("nan")]*5,[1,2]*5,sample_interval_ms=100,max_lag_samples=1)
