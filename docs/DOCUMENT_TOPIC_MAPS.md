# Document topic maps

Video topic maps use millisecond intervals. Document topic maps deliberately use a separate
page-native hierarchy so PDF pages are never forced into fake timestamps.

## Data model

- A document topic belongs to one source and can have a parent topic from that same source.
- Topic order is explicit and stable through an ordinal.
- Provenance and review state remain separate.
- Topic/evidence relationships point to unified evidence-reference IDs.
- The database prevents a topic from citing a page belonging to another source.
- The outline returns the page number and asset identity alongside each citation.

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

This is an initial PDF-page-oriented slice. It does not yet automatically discover topics or
compose document topics into textbook chapters.

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

Composition creates chapters from accepted document topics and adds only claims whose exact same
evidence-reference ID is accepted by both the topic and the claim. It carries that citation into
the textbook block. It does not generate new prose, infer unsupported relationships or bypass the
publication auditor.

