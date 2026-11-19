from pathlib import Path

from omniintel.collections import CollectionStore
from omniintel.course_export import CourseTextbookExporter
from omniintel.course_textbook import CourseTextbookStore
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore


def test_course_textbook_exports_all_formats_with_provenance(tmp_path: Path) -> None:
    db=tmp_path/"course.sqlite"
    source=OmniIntelStore(db).import_transcript(TranscriptImport(
        title="Lecture: Mechanics",
        segments=(TranscriptSegmentInput("Newton's first law",1000,2500),),
    ))
    collection=CollectionStore(db).create("Physics")
    CollectionStore(db).add_source(collection,source.source_id)
    store=CourseTextbookStore(db)
    book=store.create(collection,"Physics Course")
    version=store.create_version(book,"Complete textbook")
    chapter=store.add_chapter(version,"Inertia",ordinal=0,source_id=source.source_id,
                              summary="A source-grounded chapter.")
    block=store.add_block(chapter,"PARAGRAPH",{"text":"An object maintains its state of motion."},
                          provenance="SOURCE",review_status="ACCEPTED")
    link=store.link_evidence(block,source.evidence_ref_ids[0])
    store.review_evidence(link,"ACCEPTED")
    exporter=CourseTextbookExporter(db)
    md=exporter.export_markdown(version,tmp_path/"book.md")
    html=exporter.export_html(version,tmp_path/"book.html")
    pdf=exporter.export_pdf(version,tmp_path/"book.pdf")
    docx=exporter.export_docx(version,tmp_path/"book.docx")
    for path in (md,html,pdf,docx):
        assert path.is_file() and path.stat().st_size>100
    assert "Lecture: Mechanics" in md.read_text(encoding="utf-8")
    rendered=html.read_text(encoding="utf-8")
    assert "Newton" not in rendered  # Citation uses the evidence locator, not unrelated transcript text.
    assert "Lecture: Mechanics" in rendered
