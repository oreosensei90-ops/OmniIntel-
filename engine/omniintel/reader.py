"""Source-synchronized course textbook reader with durable local positions."""
from __future__ import annotations

from collections import deque
import json
import json
from pathlib import Path
from typing import Any

from .course_textbook import CourseTextbookStore
from .database import connect, migrate
from .models import utc_now


class ReaderError(ValueError):
    pass


class SynchronizedReader:
    """Resolve evidence to its original source and an accepted course clock."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)
        self.books = CourseTextbookStore(self.database_path)

    def _clock_offsets(self, collection_id: str, anchor_source_id: str) -> dict[str, int | None]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                """SELECT source_a_id,source_b_id,offset_ms,sample_interval_ms
                   FROM source_clock_alignments
                   WHERE collection_id=? AND review_state='ACCEPTED'
                   ORDER BY created_at,id""",(collection_id,)
            ).fetchall()
        graph: dict[str,list[tuple[str,int,int]]] = {}
        for row in rows:
            a,b,offset,interval=row["source_a_id"],row["source_b_id"],row["offset_ms"],row["sample_interval_ms"]
            # Convention: t_A = t_B + offset.
            graph.setdefault(a,[]).append((b,offset,interval))
            graph.setdefault(b,[]).append((a,-offset,interval))
        offsets: dict[str,int | None]={anchor_source_id:0}
        tolerances: dict[str,int]={anchor_source_id:0}
        queue=deque([anchor_source_id])
        component={anchor_source_id}
        inconsistent=False
        while queue:
            current=queue.popleft()
            for neighbor,delta,interval in graph.get(current,[]):
                candidate_offset=int(offsets[current])+delta
                tolerance=max(tolerances[current],interval)
                if neighbor not in offsets:
                    offsets[neighbor]=candidate_offset
                    tolerances[neighbor]=tolerance
                    component.add(neighbor)
                    queue.append(neighbor)
                elif abs(int(offsets[neighbor])-candidate_offset)>max(tolerances[neighbor],tolerance):
                    inconsistent=True
        # A contradictory cycle makes the whole connected clock component unsafe.
        if inconsistent:
            for source_id in component:
                offsets[source_id]=None
        return offsets

    def open_version(
        self, version_id: str, *, anchor_source_id: str | None = None
    ) -> dict[str, Any]:
        tree=self.books.get_version(version_id)
        if tree is None:
            raise ReaderError("Course textbook version does not exist")
        collection_id=tree["version"]["collection_id"]
        with connect(self.database_path) as conn:
            members=conn.execute(
                """SELECT cs.source_id,cs.ordinal,s.title,s.duration_ms,s.language
                   FROM collection_sources cs JOIN sources s ON s.id=cs.source_id
                   WHERE cs.collection_id=? ORDER BY cs.ordinal""",(collection_id,)
            ).fetchall()
        if not members:
            raise ReaderError("Course has no source members")
        if anchor_source_id is None:
            anchor_source_id=members[0]["source_id"]
        if anchor_source_id not in {row["source_id"] for row in members}:
            raise ReaderError("Reader anchor must belong to the course collection")
        offsets=self._clock_offsets(collection_id,anchor_source_id)
        source_map={row["source_id"]:dict(row) for row in members}
        chapters=[]
        for entry in tree["chapters"]:
            chapter=entry["chapter"]
            blocks=[]
            for block in entry["blocks"]:
                evidence=[]
                for link in block["evidence"]:
                    source_id=link["source_id"]
                    start=link["start_ms"]
                    mapped=None
                    mapped_end=None
                    offset=offsets.get(source_id)
                    if start is not None and offset is not None:
                        mapped=start+int(offset)
                        if link["end_ms"] is not None:
                            mapped_end=int(link["end_ms"])+int(offset)
                    excerpt=[]
                    if link["locator_kind"]=="TRANSCRIPT_INTERVAL":
                        with connect(self.database_path) as conn:
                            rows=conn.execute(
                                """SELECT text,start_ms,end_ms,speaker_id FROM transcript_segments
                                   WHERE source_id=? AND start_ms<? AND end_ms>?
                                   ORDER BY ordinal LIMIT 40""",
                                (source_id,link["end_ms"],link["start_ms"]),
                            ).fetchall()
                        excerpt=[dict(row) for row in rows]
                    document_page=None
                    document_elements=[]
                    if link["locator_kind"]=="DOCUMENT_PAGE":
                        with connect(self.database_path) as conn:
                            page=conn.execute(
                                """SELECT dp.id,dp.page_number,dp.text_content,dp.extraction_status,
                                          dp.content_sha256,dp.char_count
                                   FROM evidence_refs er
                                   JOIN document_pages dp ON dp.id=er.document_page_id
                                   WHERE er.id=?""",(link["citation_id"],)
                            ).fetchone()
                            if page is not None:
                                document_page=dict(page)
                                elements=conn.execute(
                                    """SELECT id,element_type,ordinal,text_content,content_json,
                                              x0,y0,x1,y1,confidence,provenance,review_state
                                       FROM document_elements WHERE page_id=?
                                       ORDER BY ordinal,id LIMIT 100""",(page["id"],)
                                ).fetchall()
                                document_elements=[
                                    {**dict(element),"content":json.loads(element["content_json"])}
                                    for element in elements
                                ]
                    evidence.append({
                        **link,
                        "source":source_map.get(source_id),
                        "local_start_ms":start,
                        "local_end_ms":link["end_ms"],
                        "course_time_ms":mapped,
                        "course_end_time_ms":mapped_end,
                        "clock_offset_ms":offset,
                        "seek_available":start is not None,
                        "alignment_status":"ANCHOR" if source_id==anchor_source_id else (
                            "ALIGNED" if mapped is not None else "UNALIGNED_OR_AMBIGUOUS"
                        ),
                        "transcript_excerpt":excerpt,
                        "document_page":document_page,
                        "document_elements":document_elements,
                    })
                blocks.append({**block,"evidence":evidence})
            chapters.append({"chapter":chapter,"blocks":blocks})
        return {
            "version":tree["version"],
            "anchor_source_id":anchor_source_id,
            "sources":list(source_map.values()),
            "chapters":chapters,
            "alignment_policy":"Only human-accepted clock alignments are used; ambiguous paths are not mapped.",
        }

    def save_position(
        self, session_id: str, version_id: str, *, anchor_source_id: str | None,
        current_source_id: str | None, position_ms: int, chapter_id: str | None = None,
        block_id: str | None = None,
    ) -> None:
        if not session_id.strip() or position_ms<0:
            raise ReaderError("Session ID and non-negative position are required")
        with connect(self.database_path) as conn:
            tree=conn.execute(
                """SELECT t.collection_id FROM course_textbook_versions v
                   JOIN course_textbooks t ON t.id=v.textbook_id WHERE v.id=?""",(version_id,)
            ).fetchone()
            if tree is None:
                raise ReaderError("Course textbook version does not exist")
            allowed={row["source_id"] for row in conn.execute(
                "SELECT source_id FROM collection_sources WHERE collection_id=?",(tree["collection_id"],)
            ).fetchall()}
            if anchor_source_id is not None and anchor_source_id not in allowed:
                raise ReaderError("Anchor source is not in the course")
            if current_source_id is not None and current_source_id not in allowed:
                raise ReaderError("Current source is not in the course")
            if chapter_id is not None and not conn.execute(
                "SELECT 1 FROM course_textbook_chapters WHERE id=? AND version_id=?",(chapter_id,version_id)
            ).fetchone():
                raise ReaderError("Chapter does not belong to this version")
            if block_id is not None and not conn.execute(
                """SELECT 1 FROM course_textbook_blocks b JOIN course_textbook_chapters c
                   ON c.id=b.chapter_id WHERE b.id=? AND c.version_id=?""",(block_id,version_id)
            ).fetchone():
                raise ReaderError("Block does not belong to this version")
            conn.execute(
                """INSERT INTO reader_sessions
                   (id,version_id,anchor_source_id,current_source_id,position_ms,chapter_id,block_id,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     version_id=excluded.version_id,anchor_source_id=excluded.anchor_source_id,
                     current_source_id=excluded.current_source_id,position_ms=excluded.position_ms,
                     chapter_id=excluded.chapter_id,block_id=excluded.block_id,updated_at=excluded.updated_at""",
                (session_id,version_id,anchor_source_id,current_source_id,position_ms,
                 chapter_id,block_id,utc_now()),
            )

    def resume(self, session_id: str) -> dict[str, Any] | None:
        with connect(self.database_path) as conn:
            row=conn.execute("SELECT * FROM reader_sessions WHERE id=?",(session_id,)).fetchone()
        return dict(row) if row else None
