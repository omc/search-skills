---
name: bonsai-autocomplete
description: Implement a complete autocomplete solution in Elasticsearch or OpenSearch, including schema design, edge-ngram completions, word and phrase suggestions using significant_terms aggregations, post-processing middleware, and scaling strategies for millions of documents.
triggers:
  - bonsai-autocomplete
  - bonsai-autocomplete implement
  - bonsai-autocomplete setup
  - bonsai-autocomplete opensearch
  - bonsai-autocomplete elasticsearch
---
# bonsai-autocomplete

Open `@references/guide.md` and follow it. Do not proceed without it.

Implement a production-ready autocomplete solution in Elasticsearch or OpenSearch. Walks the user through schema design (edge-ngram completions, suggest_word, suggest_phrase fields), query construction using significant_terms aggregations, post-processing middleware, and scaling strategies proven to handle 6M+ documents at 500 QPS with sub-50ms latency.
