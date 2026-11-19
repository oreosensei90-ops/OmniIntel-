# Textbook Composition Model

## Purpose

The textbook is a versioned, structured learning artifact. It is not stored as one mutable Markdown string. The canonical representation is a relational document tree that can later be rendered into PDF, DOCX, HTML and Markdown without discarding evidence links or review metadata.

## Hierarchy

- A textbook belongs to one source in the initial implementation.
- Each textbook has numbered versions with a composition mode: source order, conceptual, or hybrid.
- A version contains ordered chapters; chapters may be nested.
- Chapters contain ordered blocks; blocks may be nested.
- Blocks contain JSON objects rather than renderer-specific markup.

## Block vocabulary

The initial block types are heading, paragraph, definition, equation, table, diagram, image, code, example, worked solution, warning, misconception, summary, exercise, source reference and footnote.

Block provenance is one of SOURCE, EXPLANATION, DERIVED, EXTERNAL or UNCERTAIN. Review state is independent: DRAFT, NEEDS_REVIEW, ACCEPTED or REJECTED. Provenance describes where a statement came from; review state describes whether it has been checked. Neither field substitutes for semantic evidence validation.

A block may reference a knowledge unit and/or claim. Evidence links identify source evidence and a relation (supports, illustrates, contextualizes or contradicts), with a separate review state. The database enforces that linked evidence belongs to the same source as the textbook.

## Deterministic outline composition

The initial composer creates chapters only from ACCEPTED topics. It places a claim into a chapter only when the same evidence item has both an ACCEPTED topic/evidence link and an ACCEPTED SUPPORTS claim/evidence link, and the claim status is SUPPORTED. Claims with accepted contradictions are excluded. Evidence links are copied to the resulting block as accepted SUPPORTS references.

This composer performs no language-model generation and invents no connective prose. A topic with no qualifying claims remains an empty chapter with its source time range and topic description. Topic hierarchy is preserved where accepted parents exist; unaccepted ancestors are skipped in favor of the nearest accepted ancestor. Cyclic accepted topic hierarchies fail rather than producing a malformed document.

## Integrity rules

- Version numbers are unique within a textbook.
- Chapter ordinals are unique within a version.
- Block ordinals are unique among siblings, including root blocks.
- Parent chapters stay within the same version; parent blocks stay within the same chapter.
- Parent hierarchy updates cannot introduce cycles.
- JSON block payloads must be objects and reject non-finite numeric values at the Python boundary.
- Evidence cannot be linked across source boundaries.

## Current scope and limitations

Implemented: persistence, version numbering, structured block vocabulary, provenance/review metadata, evidence links, source-boundary guards, sibling ordering, hierarchy-cycle guards and deterministic evidence-gated topic-to-chapter composition.

Not implemented yet: automated topic discovery, semantic claim-to-topic relevance validation, semantic block validation, immutable published-version enforcement, rendering/export, diagrams/equation rendering, annotation remapping or multi-source textbooks. A stored block is not automatically accurate or publication-ready. Exporters must preserve provenance and citations, and must not silently publish UNCERTAIN or unreviewed material.
