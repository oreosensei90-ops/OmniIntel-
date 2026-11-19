"""Deterministic offline metrics for OmniIntel quality benchmark fixtures."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Sequence

from .database import connect, migrate
from .ids import uuid7
from .models import utc_now


def _normalize(text: str) -> list[str]:
    value=unicodedata.normalize("NFKC",text).casefold()
    return re.findall(r"\w+|[^\w\s]",value,flags=re.UNICODE)


def _edit_distance(a: Sequence[str], b: Sequence[str]) -> int:
    previous=list(range(len(b)+1))
    for i,left in enumerate(a,1):
        current=[i]
        for j,right in enumerate(b,1):
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(left!=right)))
        previous=current
    return previous[-1]


def error_rate(reference: str, hypothesis: str, *, character: bool = False) -> float:
    """Compute WER or CER; empty references are explicitly undefined (None)."""
    ref=list(unicodedata.normalize("NFKC",reference).casefold()) if character else _normalize(reference)
    hyp=list(unicodedata.normalize("NFKC",hypothesis).casefold()) if character else _normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref,hyp)/len(ref)


def timestamp_mae_ms(reference: Sequence[tuple[int,int]], hypothesis: Sequence[tuple[int,int]]) -> float | None:
    """Mean absolute boundary error for positionally matched segment pairs."""
    if not reference or not hypothesis:
        return None
    count=min(len(reference),len(hypothesis))
    errors=[]
    for expected,actual in zip(reference[:count],hypothesis[:count]):
        if expected[1]<expected[0] or actual[1]<actual[0]:
            raise ValueError("Segment timestamps must have end >= start")
        errors.extend((abs(expected[0]-actual[0]),abs(expected[1]-actual[1])))
    return sum(errors)/len(errors)


def set_precision_recall(expected: Iterable[str], actual: Iterable[str]) -> dict[str,float]:
    truth,pred=set(expected),set(actual)
    tp=len(truth & pred)
    precision=tp/len(pred) if pred else (1.0 if not truth else 0.0)
    recall=tp/len(truth) if truth else (1.0 if not pred else 0.0)
    return {"precision":precision,"recall":recall,"f1":(2*precision*recall/(precision+recall) if precision+recall else 0.0)}


def section_coverage(expected_sections: Iterable[str], generated_sections: Iterable[str]) -> dict[str,float]:
    return set_precision_recall(expected_sections,generated_sections)


def evaluate_case(case: dict[str,Any]) -> dict[str,Any]:
    """Evaluate a fixture; no model/provider call is made."""
    result={"case_id":str(case.get("case_id","unnamed")),"metrics":{}}
    if "transcript_reference" in case and "transcript_hypothesis" in case:
        result["metrics"]["wer"]=error_rate(case["transcript_reference"],case["transcript_hypothesis"])
        result["metrics"]["cer"]=error_rate(case["transcript_reference"],case["transcript_hypothesis"],character=True)
    if "reference_segments" in case and "hypothesis_segments" in case:
        result["metrics"]["timestamp_mae_ms"]=timestamp_mae_ms(
            [tuple(x) for x in case["reference_segments"]],
            [tuple(x) for x in case["hypothesis_segments"]],
        )
    for key in ("evidence_ids","section_ids"):
        ref_key=f"expected_{key}"
        actual_key=f"actual_{key}"
        if ref_key in case and actual_key in case:
            result["metrics"][key]=set_precision_recall(case[ref_key],case[actual_key])
    if "alignment_offset_ms" in case and "expected_offset_ms" in case:
        result["metrics"]["alignment_abs_error_ms"]=abs(
            int(case["alignment_offset_ms"])-int(case["expected_offset_ms"])
        )
    if "ocr_reference" in case and "ocr_hypothesis" in case:
        result["metrics"]["ocr_cer"]=error_rate(case["ocr_reference"],case["ocr_hypothesis"],character=True)
    return result


def evaluate_suite(cases: Sequence[dict[str,Any]]) -> dict[str,Any]:
    if not cases:
        raise ValueError("Benchmark suite must contain at least one case")
    results=[evaluate_case(case) for case in cases]
    metric_values: dict[str,list[float]]={}
    for result in results:
        for key,value in result["metrics"].items():
            if isinstance(value,(int,float)):
                metric_values.setdefault(key,[]).append(float(value))
            elif isinstance(value,dict):
                for subkey,subvalue in value.items():
                    metric_values.setdefault(f"{key}.{subkey}",[]).append(float(subvalue))
    aggregates={key:{"mean":sum(values)/len(values),"count":len(values)}
                for key,values in sorted(metric_values.items()) if values}
    return {"schema_version":1,"case_count":len(results),"aggregates":aggregates,"cases":results}


class QualityBenchmarkStore:
    def __init__(self,database_path: str | Path):
        self.database_path=Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)

    def record(self,suite_name: str,report: dict[str,Any],*,dataset_version: str) -> str:
        if not suite_name.strip() or not dataset_version.strip():
            raise ValueError("Suite name and dataset version are required")
        encoded=json.dumps(report,ensure_ascii=False,sort_keys=True,allow_nan=False)
        run_id=uuid7()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO quality_benchmark_runs
                   (id,suite_name,dataset_version,report_json,created_at)
                   VALUES(?,?,?,?,?)""",
                (run_id,suite_name.strip(),dataset_version.strip(),encoded,utc_now()),
            )
        return run_id

    def list_runs(self,suite_name: str | None = None) -> list[dict[str,Any]]:
        with connect(self.database_path) as conn:
            if suite_name:
                rows=conn.execute(
                    "SELECT * FROM quality_benchmark_runs WHERE suite_name=? ORDER BY created_at DESC",
                    (suite_name,),
                ).fetchall()
            else:
                rows=conn.execute("SELECT * FROM quality_benchmark_runs ORDER BY created_at DESC").fetchall()
        return [{**dict(row),"report":json.loads(row["report_json"])} for row in rows]
