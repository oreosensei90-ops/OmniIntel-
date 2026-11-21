#!/usr/bin/env python3
"""Offline end-to-end harness: client -> API contract -> bridge -> REAL engine -> artifact -> client.

REAL: omniintel.cloud_worker_bridge (HTTP, lease, heartbeat, fail/complete), JobQueue, worker.run_once,
      caption parsing, evidence, textbook composition, ffmpeg audio extraction, reader export, validation.
MOCKED (network boundaries that do not exist offline): the Cloudflare Worker/D1/B2 (an in-memory server that
      implements the same HTTP contract as infra/cloudflare/worker/src/index.ts), yt-dlp, and the Whisper model.
This does NOT prove the live deployment; it proves the engine<->API protocol and that outputs are usable.
"""
from __future__ import annotations

import json, os, subprocess, sys, tempfile, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import urllib.request, urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import omniintel.cloud_worker_bridge as bridge          # noqa: E402
import omniintel.youtube_pipeline as yp                 # noqa: E402
import omniintel.worker as engine_worker                # noqa: E402
from omniintel.models import TranscriptSegmentInput     # noqa: E402
from omniintel.transcription import ChunkTranscription  # noqa: E402

API_TOKEN, WORKER_TOKEN = "api-token-test", "worker-token-test"
JOBS: dict[str, dict] = {}
OBJECTS: dict[str, bytes] = {}
LOCK = threading.Lock()
VTT = "WEBVTT\n\n" + "".join(
    f"00:{(i*5)//60:02d}:{(i*5)%60:02d}.000 --> 00:{(i*5+4)//60:02d}:{(i*5+4)%60:02d}.000\n{t}\n\n"
    for i, t in enumerate([
        "Photosynthesis converts Light Energy into Chemical Energy.",
        "Chlorophyll absorbs Light Energy in the Chloroplast.",
        "The Calvin Cycle fixes carbon dioxide into sugar.",
        "Light Energy drives the first stage of Photosynthesis.",
        "Sugar stores Chemical Energy for the plant.",
    ]))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def _body(self):
        n = int(self.headers.get("content-length") or 0); return self.rfile.read(n) if n else b""
    def _auth(self, expected):
        return self.headers.get("authorization") == "Bearer " + expected
    def do_PUT(self):
        if self.path.startswith("/b2/"):
            OBJECTS[self.path.split("?")[0]] = self._body(); return self._send(200, b"")
        self._send(404, {"error": "Not found"})
    def do_GET(self):
        if self.path.startswith("/b2/"):
            return self._send(200, OBJECTS[self.path.split("?")[0]]) if self.path.split("?")[0] in OBJECTS else self._send(404, b"")
        if not self._auth(API_TOKEN): return self._send(401, {"error": "A valid bearer token is required"})
        job = JOBS.get(self.path.rsplit("/", 1)[-1])
        if not job: return self._send(404, {"error": "Job not found"})
        out = {"job_id": job["id"], "status": job["state"], "attempt": job["attempt"], "error": job["error"]}
        if job["result_key"]: out["result_url"] = f"http://127.0.0.1:{self.server.server_port}{job['result_key']}"
        self._send(200, out)
    def do_POST(self):
        p, body = self.path, self._body()
        worker_route = p.startswith("/v1/worker/")
        if not self._auth(WORKER_TOKEN if worker_route else API_TOKEN):
            return self._send(401, {"error": "A valid bearer token is required"})
        data = json.loads(body or b"{}")
        port = self.server.server_port
        with LOCK:
            if p in ("/v1/youtube/jobs", "/v1/media/jobs"):
                yt = p.endswith("youtube/jobs")
                if yt and data.get("approve_network") is not True:
                    return self._send(400, {"error": "Explicit network approval is required."})
                if not yt and data.get("approve_media_upload") is not True:
                    return self._send(400, {"error": "Explicit media-upload approval is required."})
                jid = str(uuid.uuid4()); key = f"/b2/inputs/{jid}"
                JOBS[jid] = {"id": jid, "type": "YOUTUBE_TO_NOTES" if yt else "UPLOADED_MEDIA_TO_NOTES",
                             "payload": data, "state": "QUEUED", "attempt": 0, "error": None, "result_key": None,
                             "input_key": None if yt else key, "uploaded": yt, "lease": None, "max": 2}
                r = {"job_id": jid, "status": "QUEUED" if yt else "AWAITING_UPLOAD", "status_url": f"/v1/jobs/{jid}"}
                if not yt: r.update(upload_url=f"http://127.0.0.1:{port}{key}?sig", upload_complete_url=f"/v1/jobs/{jid}/upload-complete")
                return self._send(202, r)
            if p.endswith("/upload-complete"):
                job = JOBS[p.split("/")[3]]
                if job["input_key"] not in OBJECTS: return self._send(409, {"error": "Uploaded object is not available yet"})
                job["uploaded"] = True; return self._send(200, {"job_id": job["id"], "status": "QUEUED"})
            if p == "/v1/worker/claim":
                for job in JOBS.values():
                    if job["state"] == "QUEUED" and job["uploaded"] and job["attempt"] < job["max"] and job.get("not_before", 0) <= time.time():
                        job.update(state="RUNNING", attempt=job["attempt"] + 1, lease=str(uuid.uuid4()))
                        out = {"job_id": job["id"], "job_type": job["type"], "payload": job["payload"],
                               "lease_token": job["lease"], "attempt": job["attempt"]}
                        if job["input_key"]: out["download_url"] = f"http://127.0.0.1:{port}{job['input_key']}"
                        return self._send(200, {"job": out})
                return self._send(200, {"job": None})
            parts = p.split("/")  # /v1/worker/jobs/<id>/<action>
            job = JOBS.get(parts[4]) if len(parts) == 6 else None
            if not job or job["state"] != "RUNNING" or job["lease"] != data.get("lease_token"):
                return self._send(409, {"error": "Lease lost or job is no longer running"})
            if parts[5] == "heartbeat": return self._send(200, {"job_id": job["id"]})
            if parts[5] == "fail":
                job["error"] = data["error"]; job["lease"] = None
                job["state"] = "QUEUED" if job["attempt"] < job["max"] else "FAILED"; job["not_before"] = time.time() + 30  # mirrors the Worker's retry backoff
                return self._send(200, {"status": "REQUEUED_OR_FAILED"})
            if parts[5] == "complete":
                key = f"/b2/readers/{job['id']}/{job['lease']}/reader.json"
                OBJECTS[key] = json.dumps(data["reader"]).encode()
                job.update(state="COMPLETED", result_key=key, lease=None)
                return self._send(200, {"status": "COMPLETED", "result_key": key})
        self._send(404, {"error": "Not found"})


def call(base, token, path, method="GET", body=None):
    req = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


class FakeWhisper:
    name, version, model_id = "fake-whisper", "1", "tiny"
    def __init__(self, **_): pass
    def transcribe_chunk(self, wav_path, *, language):
        return ChunkTranscription("en", (
            TranscriptSegmentInput(text="Welcome to the lecture on cell energy.", start_ms=0, end_ms=4000, language="en"),
            TranscriptSegmentInput(text="Mitochondria produce ATP through Cellular Respiration.", start_ms=4000, end_ms=9000, language="en"),
            TranscriptSegmentInput(text="Cellular Respiration needs oxygen and glucose.", start_ms=9000, end_ms=14000, language="en"),
        ))


def drain(base, work: Path):
    """Run the real bridge until the queue is empty. Returns how many jobs were attempted."""
    n = 0
    while True:
        try:
            worked = bridge.run_bridge_once(api_base=base, worker_token=WORKER_TOKEN, database=work / "w.sqlite3",
                                            upload_dir=work / "up", asset_dir=work / "assets")
        except bridge.BridgeError as e:
            print("   bridge reported:", str(e)[:160]); worked = True
        if not worked: return n
        n += 1


def main() -> int:
    out = Path(os.environ.get("E2E_OUT", tempfile.mkdtemp(prefix="omniintel-e2e-")))
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="omniintel-work-"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler); threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    results = []
    def check(ok, msg): ok = bool(ok); results.append(ok); print(("PASS " if ok else "FAIL ") + msg)

    # network-boundary stubs
    yp.inspect_video = lambda url: {"video_id": "dQw4w9WgXcQ", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                                    "title": "Photosynthesis in 30 seconds", "uploader": "Demo", "duration_ms": 25000,
                                    "language": "en", "description": "", "availability": "public"}
    yp.fetch_public_captions = lambda url, language=None: (VTT, "en")
    engine_worker.FasterWhisperAdapter = FakeWhisper
    os.environ.update(OMNIINTEL_ASR_MODEL_ID="tiny", OMNIINTEL_ASR_ALLOW_MODEL_DOWNLOAD="1")
    def local_download(url, dest, max_bytes=bridge._MAX_UPLOAD):
        with urllib.request.urlopen(url, timeout=30) as r: data = r.read()
        if not data: raise bridge.BridgeError("Uploaded media object is empty.")
        dest.write_bytes(data); return len(data)
    bridge._download_input = local_download

    print("\n== AUTH ==")
    check(call(base, "wrong", "/v1/youtube/jobs", "POST", {})[0] == 401, "bad API token -> 401")
    check(call(base, WORKER_TOKEN, "/v1/youtube/jobs", "POST", {})[0] == 401, "worker token rejected on client route")
    check(call(base, API_TOKEN, "/v1/worker/claim", "POST", {})[0] == 401, "API token rejected on worker route")
    check(call(base, API_TOKEN, "/v1/youtube/jobs", "POST", {"url": "https://youtu.be/x", "approve_network": False})[0] == 400, "missing consent -> 400")

    print("\n== YOUTUBE: submit -> claim -> captions -> textbook -> artifact -> retrieve ==")
    code, created = call(base, API_TOKEN, "/v1/youtube/jobs", "POST", {
        "url": "https://youtu.be/dQw4w9WgXcQ", "approve_network": True, "approve_ai": False, "chapter_minutes": 10})
    check(code == 202 and created["status"] == "QUEUED", "job accepted and QUEUED")
    check(call(base, API_TOKEN, created["status_url"])[1]["status"] == "QUEUED", "status is QUEUED before a worker runs (attempt 0)")
    drain(base, work)
    code, job = call(base, API_TOKEN, created["status_url"])
    check(job["status"] == "COMPLETED" and job["attempt"] == 1, f"job COMPLETED on attempt 1 (status={job['status']} err={job['error']})")
    reader = json.loads(urllib.request.urlopen(job["result_url"]).read())
    (out / "youtube.reader.json").write_text(json.dumps(reader, ensure_ascii=False, indent=1))
    blocks = [b for c in reader["chapters"] for b in c["blocks"]]
    check(len(blocks) > 3 and all(b["evidence"] for b in blocks if b["block_type"] == "PARAGRAPH"), f"reader has {len(blocks)} blocks; paragraphs carry evidence")
    check(reader["pipeline"]["transcript_origin"] == "caption", "origin recorded as caption")

    print("\n== AUDIO UPLOAD: intent -> PUT -> finalize -> claim -> ASR -> reader -> retrieve ==")
    mp3 = work / "tone.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=15", "-q:a", "9", str(mp3)], check=True)
    code, created = call(base, API_TOKEN, "/v1/media/jobs", "POST", {"filename": "lecture.mp3", "title": "lecture.mp3",
                         "approve_media_upload": True, "approve_ai": False, "approve_visual": False, "chapter_minutes": 10})
    check(code == 202 and created["status"] == "AWAITING_UPLOAD" and created["upload_url"], "upload intent returns signed PUT URL")
    check(drain(base, work) == 0, "worker does NOT claim a job before upload is finalized")
    check(call(base, API_TOKEN, created["upload_complete_url"], "POST", {})[0] == 409, "finalize before PUT -> 409 'not available yet'")
    req = urllib.request.Request(created["upload_url"], method="PUT", data=mp3.read_bytes(), headers={"Content-Type": "audio/mpeg"})
    check(urllib.request.urlopen(req).status == 200, "browser-style PUT of the MP3 succeeded")
    check(call(base, API_TOKEN, created["upload_complete_url"], "POST", {})[0] == 200, "finalize accepted")
    drain(base, work)
    code, job = call(base, API_TOKEN, created["status_url"])
    check(job["status"] == "COMPLETED", f"audio job COMPLETED (status={job['status']} err={job['error']})")
    reader = json.loads(urllib.request.urlopen(job["result_url"]).read())
    (out / "audio.reader.json").write_text(json.dumps(reader, ensure_ascii=False, indent=1))
    check(any("Mitochondria" in json.dumps(b["content"]) for c in reader["chapters"] for b in c["blocks"]), "ASR transcript text is present in the reader")
    check(not list((work / "up").glob("*")), "uploaded media deleted from worker disk after processing")

    print("\n== FAILURE / RETRY / EXPIRY ==")
    yp.fetch_public_captions = lambda url, language=None: (_ for _ in ()).throw(RuntimeError("No public captions were available in the selected languages."))
    os.environ.pop("OMNIINTEL_ASR_MODEL_ID")  # make the ASR fallback fail deterministically
    code, created = call(base, API_TOKEN, "/v1/youtube/jobs", "POST", {"url": "https://youtu.be/aaaaaaaaaaa", "approve_network": True})
    drain(base, work)
    job = call(base, API_TOKEN, created["status_url"])[1]
    check(job["status"] == "QUEUED" and job["attempt"] == 1 and job["error"],
          f"1st failure re-queued with backoff and a readable error: {str(job['error'])[:100]}")
    check(drain(base, work) == 0, "job is NOT re-claimed during its backoff window")
    JOBS[created["job_id"]]["not_before"] = 0  # time passes
    drain(base, work)
    job = call(base, API_TOKEN, created["status_url"])[1]
    check(job["status"] == "FAILED" and job["attempt"] == 2, "2nd failure -> FAILED (max_attempts honoured)")
    check(call(base, API_TOKEN, "/v1/worker/claim", "POST", {})[0] == 401, "claim still protected")

    print("\n== AI PROVIDER OUTAGE DOES NOT DISCARD THE NOTES ==")
    yp.fetch_public_captions = lambda url, language=None: (VTT, "en")
    os.environ["OMNIINTEL_AI_PROVIDER"] = "openai"
    engine_worker.resolve_study_generator = lambda p: (_ for _ in ()).throw(RuntimeError("provider unreachable"))
    code, created = call(base, API_TOKEN, "/v1/youtube/jobs", "POST", {"url": "https://youtu.be/bbbbbbbbbbb", "approve_network": True, "approve_ai": True})
    drain(base, work)
    job = call(base, API_TOKEN, created["status_url"])[1]
    check(job["status"] == "COMPLETED", "approve_ai + provider outage still COMPLETES with the extractive reader")
    r = json.loads(urllib.request.urlopen(job["result_url"]).read())
    check("ai_error" in r["pipeline"], "reader records pipeline.ai_error for the client")

    print(f"\n{sum(results)}/{len(results)} checks passed; artifacts in {out}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
