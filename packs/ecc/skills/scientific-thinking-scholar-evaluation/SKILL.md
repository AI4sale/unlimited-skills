---
name: scholar-evaluation
description: "Structured scholarly-work evaluation for papers, proposals, literature reviews, methods sections, evidence quality, citation support, and research-writing feedback."
version: 1.0.0
category: ecc
tags: "[scholar-evaluation, structured, scholarly-work, evaluation, papers, proposals, literature, reviews]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\scientific-thinking-scholar-evaluation\SKILL.md
source_sha256: cb722947dbbc63c5ce8d68f9d7c943e08caba921c2328085567c523cd13496c9
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:59Z"
---

## When to Use

- Reviewing a research paper, proposal, thesis chapter, or literature review.
- Checking whether claims are supported by cited evidence.
- Evaluating methodology, study design, analysis, or limitations.
- Comparing two or more papers for quality or relevance.
- Producing structured feedback for revision.

## When Not to Use

Not specified by the source skill.

## Required Context

Not specified by the source skill.

## Procedure

1. Read the preserved source skill body below.
2. Apply only the parts relevant to the current task.
3. Verify the result using the regression tests or project-specific checks.

## Tools

Not specified by the source skill.

## Expected Output

Not specified by the source skill.

## Known Traps

- Do not use the score as a substitute for concrete feedback.
- Do not penalize a paper for omitting a dimension outside its scope.
- Do not treat citation count, venue, or author reputation as proof of quality.
- Do not accept unsupported claims just because they appear in the abstract.

## Examples of Successful Execution

Not specified by the source skill.

## Regression Tests

Not specified by the source skill.

## Original Skill Body

## Scholar Evaluation

Use this skill to evaluate academic or scientific work with a repeatable rubric.

## Evaluation Scope

Start by identifying the artifact:

- empirical research paper
- theoretical paper
- technical report
- systematic or narrative literature review
- research proposal
- thesis or dissertation chapter
- conference abstract or short paper

Then choose scope:

- **comprehensive**: all rubric dimensions
- **targeted**: one or two dimensions, such as method or citations
- **comparative**: rank multiple works against the same rubric

## Rubric

Score each applicable dimension from 1 to 5:

- 5: excellent; clear, rigorous, and publication-ready
- 4: good; minor improvements needed
- 3: adequate; meaningful gaps but usable
- 2: weak; substantial revision needed
- 1: poor; major validity or clarity problems

Use `N/A` for dimensions that do not apply.

## 1. Problem and Research Question

- Is the problem clear and specific?
- Is the contribution meaningful?
- Are scope and assumptions explicit?
- Does the question match the claimed contribution?

## 2. Literature and Context

- Is relevant prior work covered?
- Does the work synthesize rather than merely list sources?
- Are gaps accurately identified?
- Are recent and foundational sources balanced?

## 3. Methodology

- Does the method answer the research question?
- Are design choices justified?
- Are variables, datasets, participants, or materials described clearly?
- Could another researcher reproduce the work?
- Are ethical and practical constraints acknowledged?

## 4. Data and Evidence

- Are data sources credible and appropriate?
- Is sample size or corpus coverage adequate?
- Are inclusion, exclusion, and preprocessing decisions documented?
- Are missing data and bias risks discussed?

## 5. Analysis

- Are statistical, qualitative, or computational methods appropriate?
- Are baselines and controls fair?
- Are uncertainty, sensitivity, or robustness checks included when needed?
- Are alternative explanations considered?

## 6. Results and Interpretation

- Are results clearly presented?
- Do claims stay within the evidence?
- Are figures, tables, and metrics understandable?
- Are negative or null results handled honestly?

## 7. Limitations and Threats to Validity

- Are limitations specific rather than generic?
- Are internal, external, construct, and conclusion-validity risks addressed?
- Does the paper distinguish speculation from demonstrated results?

## 8. Writing and Structure

- Is the argument easy to follow?
- Are sections organized around the research question?
- Are definitions and notation clear?
- Is the tone precise and scholarly?

## 9. Citations

- Do cited papers support the claims attached to them?
- Are primary sources used where possible?
- Are reviews labeled as reviews?
- Are preprints labeled as preprints?
- Are citation metadata and links correct?

## Review Process

1. Read the abstract, introduction, figures, and conclusion for claimed
   contribution.
2. Read methods and results for evidence quality.
3. Check the strongest claims against cited sources.
4. Score each applicable dimension.
5. Separate critical blockers from revision suggestions.
6. End with concrete next edits.

## Output Template

```markdown

## Overall Assessment

- Overall score: <1-5 or N/A>
- Confidence: <high | medium | low>
- Summary: <3-5 sentences>

## Dimension Scores

| Dimension | Score | Evidence | Revision priority |
| --- | ---: | --- | --- |
| Problem and question |  |  |  |
| Literature and context |  |  |  |
| Methodology |  |  |  |
| Data and evidence |  |  |  |
| Analysis |  |  |  |
| Results and interpretation |  |  |  |
| Limitations |  |  |  |
| Writing and structure |  |  |  |
| Citations |  |  |  |

## Evidence Checks Needed

```
