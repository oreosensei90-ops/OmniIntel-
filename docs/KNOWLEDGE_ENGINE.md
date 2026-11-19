# Knowledge Reconstruction Foundation

This module stores knowledge independently from source evidence. It is provider-neutral: model adapters may propose records, but they cannot make their own evidence links accepted.

## Layers

- `evidence_items` preserve source-backed material and timestamps.
- `knowledge_units` store concepts, definitions, principles, formulas, procedures and other pedagogical units.
- `claims` store atomic statements that can be reviewed independently.
- `claim_evidence` stores SUPPORTS, CONTRADICTS, QUALIFIES, CONTEXTUALIZES and ILLUSTRATES relations.
- `knowledge_relationships` stores links between knowledge units.

## Evidence review policy

New claim/evidence links start as PENDING. Pending, rejected and needs-review links do not count as accepted evidence. A claim is publishable only when it has at least one accepted SUPPORTS link and no accepted CONTRADICTS link. A claim marked UNCERTAIN or CONTESTED is not publishable as an established fact.

An accepted relation is a review decision, not proof of semantic correctness. Human review or a separately evaluated verifier must assess whether the evidence actually supports the claim. Confidence and relevance scores are signals, not substitutes for review.

## Provenance

- SOURCE: original material, stored in the evidence layer.
- EXPLANATION: an explanatory interpretation.
- DERIVED: a conclusion inferred from identified premises.
- UNCERTAIN: a claim whose support or interpretation is unresolved.
- EXTERNAL: external material, to be modeled as separately attributed evidence when that adapter is introduced.

Knowledge units and claims cannot label themselves SOURCE. This prevents generated prose from impersonating the original instructor.

## Deliberate limits

This is the deterministic persistence and gating layer, not an automatic topic extractor or semantic entailment model. It does not yet resolve contradiction scope, quantify coverage, prove mathematical derivations, or guarantee a claim is true. Those require dedicated validators and test corpora.


## Deterministic audit

`KnowledgeAuditor` reports claims without evidence, claims with accepted support, publishable claims, contested/uncertain claims, accepted contradictions, source-duration boundary violations and unused knowledge units.

Its accepted-support ratio is explicitly a property of the stored claim set. It is not a measure of how much of the original video was understood, whether a claim is true, or whether the broader subject is complete. A semantic verifier and source-level coverage analysis are still required.


## Source-scoped topic map

Topics are stored separately from claims and concepts. Each topic belongs to one source, may have a parent topic from the same source, and has a timestamp interval. Topic/evidence links must reference evidence from the same source and overlap the topic interval. Links start PENDING; accepting a link is a review action, not an automatic model decision.

The topic store is an intake and persistence boundary for future topic-discovery adapters. It does not yet discover topics automatically, infer chapter boundaries, or prove that the outline covers the full source.
