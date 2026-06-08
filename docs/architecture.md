# Architecture

Unlimited Skills is a retrieval layer for agent skills.

## Problem

An agent can have access to thousands of useful procedures, but loading all of them into the model context creates instruction noise and token waste. A better approach is to keep a small router instruction in context and move the real skill library behind a local retrieval system.

## Components

```text
agent context
  -> router SKILL.md
    -> unlimited-skills CLI or daemon
      -> lexical JSON index
      -> vector sidecar index
      -> Chroma compatibility index
      -> learning logs
      -> selected SKILL.md
```

## Retrieval pipeline

1. The agent builds a query from the task.
2. Lexical search scores exact tokens, slugs, descriptions, and body snippets.
3. Vector search embeds the query and searches the local vector sidecar first.
4. Hybrid search merges both result sets and reranks.
5. The agent loads only the selected `SKILL.md`.

Pure vector search is not enough. It catches semantic matches but can produce false positives. Pure lexical search is fast and precise but misses intent. Hybrid search is the default because it combines both.

`vector-reindex` also writes a ChromaDB compatibility index under `.chroma-skills/`, but normal query-time vector search uses `.unlimited-skills-vectors.json` first. This avoids paying Chroma client startup cost on every CLI search.

## Warm daemon

The CLI is simple and reliable, but every vector query starts a new Python process and reloads the embedding model. The daemon keeps the model warm. The first vector query in a daemon process warms the cache; later vector and hybrid queries reuse the same embedding model.

Current daemon endpoints:

- `GET /health`
- `POST /search`
- `GET /skills/{name}`
- `POST /use`
- `POST /feedback`

The daemon is experimental, but it is the right architecture for libraries with thousands of skills.

## Learning loop

The learning loop records:

- searches;
- viewed skills;
- used skills;
- accepted matches;
- rejected matches;
- draft skill creation.

This data can later drive:

- better descriptions;
- query expansion rules;
- per-agent routing preferences;
- automatic skill drafts for repeated workflows.

The current implementation records the raw local evidence first. Automated rewriting should be conservative and reviewable.
