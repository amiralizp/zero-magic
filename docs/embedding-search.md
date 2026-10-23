# Embedding-based PRD search

Local hashing embeddings, 1024 dimensions, cosine similarity.
Documents are embedded once; each query is embedded at search time.

| Query | Expected | Top 1 | Score | Top 2 | Top 3 |
| --- | --- | --- | ---: | --- | --- |
| rate limit breakdown requests | prd-06 (Rate limit the public API) | prd-06 | 0.23 | prd-05 (0.10) | prd-11 (0.09) |
| email a large export | prd-04 (Email large exports) | prd-04 | 0.43 | prd-19 (0.42) | prd-10 (0.33) |
| assign a card to one person | prd-02 (Card assignment) | prd-02 | 0.54 | prd-08 (0.48) | prd-23 (0.40) |
| keyboard focus label contrast | prd-23 (Keyboard and screen reader access) | prd-23 | 0.27 | prd-18 (0.07) | prd-07 (0.07) |
| webhook retry backoff signature | prd-24 (Webhook delivery) | prd-24 | 0.29 | prd-06 (0.06) | prd-04 (0.04) |
| نظرات کارت | prd-13 (نظرات کارت) | prd-13 | 0.41 | prd-01 (0.00) | prd-02 (0.00) |

Top-1 accuracy on these probes: 6/6.

## How it works

1. Tokenise on words and Persian/Arabic letter runs, case-folded.
2. Hash each token into one of 1024 dimensions with a signed contribution.
3. L2-normalise the vector so long PRDs are not favoured by length alone.
4. Score a query with the dot product, which equals cosine similarity for
   normalised vectors.

## Limits and the next step

- This is lexical: `owner` does not retrieve `assignee` unless both words
  appear. A real embedding model fixes that, at the cost of a network call
  and a per-token bill.
- No index is built for 25 documents. At a few thousand PRDs, store the
  vectors in pgvector (week 5) and use an HNSW index; the `rank` interface
  stays the same.
- Similarity is not permission. Search results must still be filtered by
  the actor's workspace and role before they are returned.
