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


def test_execution_rejects_stage_for_wrong_modality(tmp_path: Path) -> None:
    path=tmp_path/"a.wav"
    plan=make_plan(path)
    executor=PlanExecutor(tmp_path/"db.sqlite")
    with pytest.raises(PlanExecutionError,match="incompatible"):
        executor.approve_and_run(
            plan,[{"stage":"SAMPLE_VIDEO_FRAMES","input_indices":[0]}],
            user_approved=True,handlers={"SAMPLE_VIDEO_FRAMES":lambda *_:{}},
        )


def test_execution_retries_failed_checkpoint_without_losing_stage_identity(tmp_path: Path) -> None:
    plan=make_plan(tmp_path/"retry.wav")
    executor=PlanExecutor(tmp_path/"db.sqlite")
    calls=[]
    def flaky(paths,context):
        calls.append(context["stage"])
        if len(calls)==1:
            raise RuntimeError("simulated adapter interruption")
        return {"recovered":True}
    stages=[{"stage":"REGISTER_SOURCE","input_indices":[0]}]
    handlers={"REGISTER_SOURCE":flaky}
    with pytest.raises(RuntimeError,match="interruption"):
        executor.approve_and_run(plan,stages,user_approved=True,handlers=handlers)
    resumed=executor.approve_and_run(plan,stages,user_approved=True,handlers=handlers)
    assert resumed["status"]=="COMPLETED"
    assert calls==["REGISTER_SOURCE","REGISTER_SOURCE"]


def test_execution_reuses_completed_stages_when_later_stage_fails(tmp_path: Path) -> None:
    plan=make_plan(tmp_path/"multi.wav")
    executor=PlanExecutor(tmp_path/"db.sqlite")
    calls=[]
    fail_once={"value":True}
    def register(paths,context):
        calls.append("register")
        return {"source_id":"source-1"}
    def transcribe(paths,context):
        calls.append("transcribe")
        if fail_once["value"]:
            fail_once["value"]=False
            raise RuntimeError("temporary transcription failure")
        return {"segments":1}
    stages=[
        {"stage":"REGISTER_SOURCE","input_indices":[0]},
        {"stage":"TRANSCRIBE_LOCAL","input_indices":[0]},
    ]
    handlers={"REGISTER_SOURCE":register,"TRANSCRIBE_LOCAL":transcribe}
    with pytest.raises(RuntimeError,match="temporary"):
        executor.approve_and_run(plan,stages,user_approved=True,handlers=handlers)
    result=executor.approve_and_run(plan,stages,user_approved=True,handlers=handlers)
    assert result["status"]=="COMPLETED"
    assert calls==["register","transcribe","transcribe"]


def test_execution_reserves_stable_source_effect_ids(tmp_path: Path) -> None:
    plan=make_plan(tmp_path/"effect.wav")
    executor=PlanExecutor(tmp_path/"db.sqlite")
    result=executor.approve_and_run(
        plan,[{"stage":"REGISTER_SOURCE","input_indices":[0]}],
        user_approved=True,handlers={"REGISTER_SOURCE":lambda *_:{"ok":True}},
    )
    first=executor.reserve_source_id(result["plan_id"],"0:REGISTER_SOURCE","a"*64)
    again=executor.reserve_source_id(result["plan_id"],"0:REGISTER_SOURCE","a"*64)
    other=executor.reserve_source_id(result["plan_id"],"0:REGISTER_SOURCE","b"*64)
    assert first==again
    assert first!=other


def test_registration_stage_does_not_misclassify_caption_files(tmp_path: Path) -> None:
    path=tmp_path/"lesson.srt"
    path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n",encoding="utf-8")
    from omniintel.input_plan import plan_local_inputs

    plan=plan_local_inputs([path]).to_dict()
    # Caption association and language are separate user decisions; even after planning,
    # generic source registration is not allowed to pretend captions are a media source.
    executor=PlanExecutor(tmp_path/"db.sqlite")
    plan["questions"]=[]
    with pytest.raises(PlanExecutionError,match="incompatible"):
        executor.approve_and_run(
            plan,[{"stage":"REGISTER_SOURCE","input_indices":[0]}],
            user_approved=True,handlers={"REGISTER_SOURCE":lambda *_:{}},
        )
