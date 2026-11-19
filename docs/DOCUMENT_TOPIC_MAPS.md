# Document topic maps

Video topic maps use millisecond intervals. Document topic maps deliberately use a separate
page-native hierarchy so PDF pages are never forced into fake timestamps.

## Data model

- A document topic belongs to one source and can have a parent topic from that same source.
- Topic order is explicit and stable through an ordinal.
- Provenance and review state remain separate.
- Topic/evidence relationships point to unified evidence-reference IDs and may identify a precise structured page element.
- The database prevents a topic from citing a page belonging to another source.
- The outline returns the page number, asset identity and optional element type/text alongside each citation.
- Multiple elements from the same page can be linked independently to one topic.

## Python API

\`\`\`python
from omniintel.topics import (
    DocumentTopicEvidenceInput,
    DocumentTopicInput,
    TopicStore,
)

topics = TopicStore("./omniintel.db")
topic_id = topics.create_document_topic(
    DocumentTopicInput(source_id, "Conservation laws", ordinal=0)
)
link_id = topics.link_document_evidence(
    DocumentTopicEvidenceInput(topic_id, page_reference_id, "INTRODUCES")
)
topics.review_document_evidence_link(link_id, "ACCEPTED")
outline = topics.get_document_outline(source_id)
\`\`\`

Uncertain topics remain in NEEDS_REVIEW even when a link is accepted. Accepted topic evidence
records relevance review; it does not prove semantic correctness or subject completeness.

Topic discovery remains manual/review-driven; deterministic composition is implemented. The composer carries accepted native paragraphs, equations, tables and figure assets into chapters, then adds claims only when the exact same page/element citation is accepted by both the topic and the claim.

For a persisted source, the CLI can print the outline and its page references:

\`\`\`bash
omniintel document-outline ./omniintel.db SOURCE_ID
\`\`\`

## Deterministic textbook composition

Once topics and claim links are reviewed, compose a draft textbook:

\`\`\`bash
omniintel compose-document-textbook ./omniintel.db SOURCE_ID "Course textbook"
omniintel audit-textbook ./omniintel.db VERSION_ID
\`\`\`

Composition creates chapters from accepted document topics. It carries reviewed native source elements into the chapters and adds only claims whose exact same page/element citation is accepted by both the topic and the claim. It does not generate new prose, infer unsupported relationships or bypass the publication auditor.

