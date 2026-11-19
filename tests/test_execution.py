from pathlib import Path

import pytest

from omniintel.execution import PlanExecutionError, PlanExecutor


def make_plan(path: Path) -> dict:
    path.write_bytes(b"local lecture bytes")
    return {
        "schema_version": 1, "read_only": True, "questions": [],
        "inputs": [{
            "path": str(path), "byte_size": path.stat().st_size,
            "modality": "AUDIO", "media_type": "audio/wav",
        }],
    }


def test_execution_requires_explicit_approval_and_resolved_plan(tmp_path: Path) -> None:
    plan = make_plan(tmp_path / "a.wav")
    executor = PlanExecutor(tmp_path / "db.sqlite")
    with pytest.raises(PlanExecutionError, match="approval"):
        executor.approve_and_run(plan, [{"stage":"REGISTER_SOURCE","input_indices":[0]}],
                                 user_approved=False, handlers={"REGISTER_SOURCE":lambda *_:{}})
    plan["questions"] = ["Confirm language"]
    with pytest.raises(PlanExecutionError, match="questions"):
        executor.approve_and_run(plan, [{"stage":"REGISTER_SOURCE","input_indices":[0]}],
                                 user_approved=True, handlers={"REGISTER_SOURCE":lambda *_:{}})


def test_execution_is_local_only_allowlisted_and_checkpointed(tmp_path: Path) -> None:
    path=tmp_path/"a.wav"
    plan=make_plan(path)
    executor=PlanExecutor(tmp_path/"db.sqlite")
    calls=[]
    def handler(paths, context):
        calls.append((paths[0].name,context["stage"]))
        return {"registered":True}
    stages=[{"stage":"REGISTER_SOURCE","input_indices":[0],"network":"none"}]
    handlers={"REGISTER_SOURCE":handler}
    result=executor.approve_and_run(plan,stages,user_approved=True,handlers=handlers)
    again=executor.approve_and_run(plan,stages,user_approved=True,handlers=handlers)
    assert result["status"]=="COMPLETED"
    assert again["reused"] is True
    assert calls==[("a.wav","REGISTER_SOURCE")]


def test_execution_rejects_network_and_unknown_stages(tmp_path: Path) -> None:
    plan=make_plan(tmp_path/"a.wav")
    executor=PlanExecutor(tmp_path/"db.sqlite")
    handlers={"REGISTER_SOURCE":lambda *_:{}}
    with pytest.raises(PlanExecutionError,match="Network"):
        executor.approve_and_run(plan,[{"stage":"REGISTER_SOURCE","input_indices":[0],"network":"internet"}],
                                 user_approved=True,handlers=handlers)
    with pytest.raises(PlanExecutionError,match="not an available"):
        executor.approve_and_run(plan,[{"stage":"RUN_SHELL","input_indices":[0]}],
                                 user_approved=True,handlers=handlers)


def test_execution_detects_changed_input_before_start(tmp_path: Path) -> None:
    path=tmp_path/"a.wav"
    plan=make_plan(path)
    path.write_bytes(b"changed after plan")
    executor=PlanExecutor(tmp_path/"db.sqlite")
    with pytest.raises(PlanExecutionError,match="changed after planning"):
        executor.approve_and_run(plan,[{"stage":"REGISTER_SOURCE","input_indices":[0]}],
                                 user_approved=True,handlers={"REGISTER_SOURCE":lambda *_:{}})
