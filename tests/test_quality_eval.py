from pathlib import Path

import pytest

from omniintel.quality_eval import (
    QualityBenchmarkStore, error_rate, evaluate_suite, section_coverage,
    set_precision_recall, timestamp_mae_ms,
)


def test_error_rates_and_unicode_normalization() -> None:
    assert error_rate("The quick fox","the quick fox")==0
    assert error_rate("café","cafe\u0301",character=True)==0
    assert error_rate("a b","a c")==0.5
    assert error_rate("","") == 0


def test_precision_recall_coverage_and_timing() -> None:
    assert set_precision_recall(["a","b"],["a","c"])=={
        "precision":0.5,"recall":0.5,"f1":0.5,
    }
    assert section_coverage(["one","two"],["one"])["recall"]==0.5
    assert timestamp_mae_ms([(0,100),(200,300)],[(10,110),(190,310)])==10
    assert timestamp_mae_ms([],[]) is None


def test_suite_aggregates_and_persists_versioned_report(tmp_path: Path) -> None:
    report=evaluate_suite([
        {"case_id":"lecture-1","transcript_reference":"hello world",
         "transcript_hypothesis":"hello world","expected_evidence_ids":["e1"],"actual_evidence_ids":["e1"]},
        {"case_id":"lecture-2","expected_offset_ms":1000,"alignment_offset_ms":1250},
    ])
    assert report["case_count"]==2
    assert report["aggregates"]["wer"]["mean"]==0
    assert report["aggregates"]["alignment_abs_error_ms"]["mean"]==250
    store=QualityBenchmarkStore(tmp_path/"quality.sqlite")
    run=store.record("smoke",report,dataset_version="golden-v1")
    assert store.list_runs("smoke")[0]["id"]==run


def test_timestamp_validation_and_empty_suite() -> None:
    with pytest.raises(ValueError):
        timestamp_mae_ms([(10,0)],[(10,20)])
    with pytest.raises(ValueError):
        evaluate_suite([])
