# Runtime State Inventory (V2.12.1)

Complete audit of every location where the running application reads or writes
persistent or semi-persistent state, produced as the first step of Sprint
V2.12.1 ("Production Hardening & Durable Learning Infrastructure"). This is a
descriptive inventory, not a design document — see `docs/durable-learning-storage.md`
for the storage abstraction built on top of it.

Baseline commit audited: `6a096e43a770f4c385240fb4c5596910db0ef0b9`.

## Classification legend

| Class | Meaning |
|---|---|
| `EPHEMERAL_CACHE` | In-process memoization of derived data. Safe to lose on every restart; recomputed from a durable source or a static file. |
| `SESSION_ONLY` | In-process, keyed by a live customer/session ID. Intentionally not persisted — losing it on restart is an accepted UX cost, not a data-loss bug. |
| `STATIC_CONFIGURATION` | Git-tracked, read-only in production. The application never writes it; redeploys correctly reset it to the committed value. |
| `DURABLE_OPERATIONAL` | Written at runtime and required for correct customer-facing behavior across restarts/redeploys (ranking promotion state, semantic search index, per-user preference memory). |
| `DURABLE_LEARNING` | Written at runtime by the V2.12 learning engine; audit trail / rollback target / candidate reports. Loss degrades the learning system's safety guarantees (audit trail, last-known-good) even though it doesn't break customer-facing chat directly. |
| `DURABLE_ANALYTICS` | Written at runtime; diagnostic/measurement data. Loss degrades visibility and learning-signal quality but not correctness of any live response. |

## Durable / runtime-written state

| Item | Module:Line | Env var | Current default | Purpose | Write/Read profile | Atomic write? | Survive restart? | Survive redeploy? | User-derived? | Security-sensitive? | Failure impact | Class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Question analytics log | `app/main.py:6142` (write), `:6225` (read) | `ANALYTICS_LOG_PATH` | `/tmp/foodland-ai-agent/question_analytics.jsonl` | Per-question analytics (hashed client, message, intent) | Write-heavy (every chat turn) | No (append) | No | No | Yes (hashed) | Low | Lost analytics history; `/admin/analytics/*` reports reset | `DURABLE_ANALYTICS` |
| Backend error log | `app/main.py:6183` (write), `:6230` (read) | `ERROR_LOG_PATH` | `/tmp/foodland-ai-agent/backend_errors.jsonl` | Backend error events for `/admin/analytics/tasks` | Write on error only | No (append) | No | No | No | Low | Lost error history for triage | `DURABLE_ANALYTICS` |
| Taxonomy shadow log | `app/main.py:6168` (write) | `TAXONOMY_SHADOW_LOG_PATH` | `/tmp/foodland-ai-agent/taxonomy_shadow.jsonl` | Shadow-mode rice-taxonomy classification observations | Write-heavy, no live reader endpoint | No (append) | No | No | No | Low | Lost shadow-mode evidence, no customer impact | `DURABLE_ANALYTICS` |
| Raw event telemetry | `app/main.py:6205` (write), `:6235` (read); re-declared independently in `app/behavioral.py:37`, `app/fbt.py:30`, `app/learning_events.py:45` | `EVENTS_LOG_PATH` | `/data/foodland-ai-agent/events.jsonl` in production (Railway volume, verified this session); `/tmp/...` default otherwise | Impression/click/add_to_cart/no_result/etc. — feeds behavioral ranking, FBT, and the V2.12 learning engine | Both write-heavy and read-heavy (every search recomputes cached rankings from it) | No (append) | **Yes** (already on Railway volume) | **Yes** (already verified this session) | Yes (session/client keyed) | Low | Loss silently degrades behavioral ranking + learning signal quality, not an outage | `DURABLE_LEARNING` |
| User preference memory | `app/main.py:3406` (write), load at `:3372` | `USER_MEMORY_PATH` | `/tmp/foodland-ai-agent/user_memory.json` | Long-lived per-customer preference profile, whole-file JSON dict | Read once at cold start, written on every profile update | **No** — plain `write_text` overwrite, no temp+replace (the one durable JSON writer in the codebase without the atomic pattern used elsewhere) | No | No | Yes | Medium (customer preference data) | Lost personalization; a torn write under concurrent handlers could corrupt the whole file, not just the latest entry | `DURABLE_OPERATIONAL` |
| Product embeddings cache | `app/embeddings.py:95` (write) | `PRODUCT_EMBEDDINGS_PATH` | `/tmp/foodland-ai-agent/product_embeddings.json` | SKU→vector cache for semantic search | Write only on `POST /admin/embeddings/rebuild`; read-heavy per semantic-search request (in-process cached) | No (plain overwrite) | No | No | No | Low | Semantic search falls back until manually rebuilt (costs OpenAI $ to regenerate) | `DURABLE_OPERATIONAL` |
| Ranking profile versions | `app/ranking_config.py:179` (write) | `RANKING_PROFILE_DIR` | `config/ranking_profiles` (repo-relative) | Versioned `RankingProfile` JSON files | Write-rare (new candidate promotion) | No (plain write, protected instead by `overwrite=False` immutability) | No | No | No | Low | New profile versions lost, falls back to last committed version | `DURABLE_OPERATIONAL` |
| Active ranking profile pointer | `app/ranking_config.py:221-237` (write) | `RANKING_PROFILE_DIR` / `active.json` | `config/ranking_profiles/active.json` — **git-tracked**, currently pinned at `v1` | Which ranking profile version is live | Write-rare (promotion/rollback) | **Yes** (genuine temp+`os.replace`) | No | **No — actively wrong today**: git-tracked path means a real production promotion is silently reverted to the committed `v1` pointer on the next Railway redeploy | No | Medium (governs live ranking behavior) | A promoted profile silently reverts to `v1` on next deploy with no error or alert | `DURABLE_OPERATIONAL` |
| Learning ledger (audit trail) | `app/learning_lifecycle.py:68` (write) | `LEARNING_HISTORY_DIR` / `ledger.jsonl` | `config/learning_history/ledger.jsonl` (repo-relative; directory does not exist on disk in this checkout; gitignored) | Append-only lifecycle transition audit trail | Write-rare (lifecycle transitions only) | No (append, by design — entries are never edited/deleted) | No | **No** — pure data loss on redeploy (directory not tracked, not on a volume) | No | Low | Audit trail gone; cannot reconstruct why a profile was promoted/rolled back | `DURABLE_LEARNING` |
| Last-known-good config | `app/learning_lifecycle.py:112-121` (write) | `LEARNING_HISTORY_DIR` / `last_known_good.json` | `config/learning_history/last_known_good.json` | Rollback target for `rollback_to_last_known_good()` | Write-rare | **Yes** (genuine temp+`os.replace`) | No | **No** — pure data loss on redeploy | No | Medium (safety-critical rollback target) | Rollback has no target after a redeploy — directly undermines the safety guarantee V2.12 was built for | `DURABLE_LEARNING` |
| Learning cycle report | `app/learning_cycle.py:209-212` (write) | `LEARNING_REPORTS_DIR` | `learning/reports/latest.json` + `latest.md` (repo-relative, gitignored) | Latest candidate report shown by `/admin/learning/candidates` | Write on every learning-cycle run | No (plain overwrite) | No | No | No | Low | `/admin/learning/candidates` returns "no report available" placeholder until next cycle runs | `DURABLE_LEARNING` |

## Static, git-tracked configuration (read-only in production — correct as-is)

| Item | Module:Line | Env var | Path | Class |
|---|---|---|---|---|
| Merchandising rules | `app/merchandising.py:28` | `MERCHANDISING_JSON_PATH` | `data/merchandising.json` | `STATIC_CONFIGURATION` |
| Synonym tables | `app/search.py:26` | `SYNONYMS_JSON_PATH` | `data/synonyms.json` | `STATIC_CONFIGURATION` |
| Product catalog snapshot | `app/main.py:236` | `PRODUCTS_JSON_PATH` | `data/products.json` | `STATIC_CONFIGURATION` |
| Knowledge base | `app/main.py:250,9223` | `KNOWLEDGE_JSON_PATH` | `data/knowledge.json` | `STATIC_CONFIGURATION` |
| Merchant feed XML (per language) | `app/feed.py:153-160`, `app/main.py:237` | `PRODUCT_FEED_PATH_*` | repo-relative XML paths | `STATIC_CONFIGURATION` |

Note: `app/knowledge_builder.py:save_knowledge()` (lines 652-659) implements a
genuine atomic writer for `KNOWLEDGE_JSON_PATH` but has zero call sites
anywhere in the codebase — dead code, not a live write path. `app/feed.py:save_products()`
is only invoked from the standalone `app/import_feed.py` CLI script, never
from the live request path.

## In-memory-only state (never persisted — confirmed by grep, no write call anywhere)

| Item | Module:Line | Invalidation | Class |
|---|---|---|---|
| `session_memories` (V2.9 multi-turn session state) | `app/main.py:304` | `SESSION_MEMORY_TTL_SECONDS` (1800s), `SESSION_MEMORY_MAX_SESSIONS` (20000) | `SESSION_ONLY` |
| `_behavioral_rankings_cache` | `app/search.py:75` | `BEHAVIORAL_CACHE_SECONDS` (300s) | `EPHEMERAL_CACHE` |
| `_merchandising_rules_cache` | `app/search.py:49` | `MERCHANDISING_CACHE_SECONDS` (60s) | `EPHEMERAL_CACHE` |
| `_active_profile_cache` | `app/ranking_config.py:243` | `RANKING_PROFILE_CACHE_SECONDS` (60s) | `EPHEMERAL_CACHE` |
| `product_search_cache` / `autocomplete_cache` | `app/main.py:307-308` | size-bounded (512), cleared on feed refresh | `EPHEMERAL_CACHE` |
| `_product_embeddings_cache` | `app/main.py:294,350-359` | manual, via `clear_embeddings_cache()` | `EPHEMERAL_CACHE` |
| `_fbt_data_cache` | `app/main.py:289-291` | `FBT_CACHE_SECONDS` (300s) | `EPHEMERAL_CACHE` |
| `_top_questions_cache` / `_trending_products_cache` / `_facets_cache` | `app/main.py:282-297` | 60s / 300s / 600s | `EPHEMERAL_CACHE` |
| Rate-limit sliding windows (5 deque sets) | `app/main.py:278-281,293` | size-capped at 50,000 clients | `EPHEMERAL_CACHE` |

## Key findings that drive Part A design

1. **`EVENTS_LOG_PATH` is the only durable-class item already correctly on a
   persistent volume**, verified this session across a real Railway restart
   and redeploy. Every other `DURABLE_*` item is still on `/tmp` or an
   unmounted repo-relative path.
2. **`config/ranking_profiles/active.json` is git-tracked**, so it is not
   merely "not yet durable" — it is actively wrong: any real production
   promotion is silently reverted to the committed `v1` pointer on the very
   next Railway redeploy, with no error surfaced anywhere. This is the
   highest-priority fix in Part A.
3. **`config/learning_history/` is gitignored and not on a volume**, and
   currently does not even exist in this checkout — a redeploy today would
   start the audit ledger and rollback target empty. Different failure mode
   than (2): data loss, not reversion-to-stale-value.
4. **`USER_MEMORY_PATH` is the one durable JSON writer without an atomic
   temp+replace pattern** (`ranking_config.py` and `learning_lifecycle.py`
   both already have one to copy).
5. Four modules (`main.py`, `behavioral.py`, `fbt.py`, `learning_events.py`)
   each independently hardcode `Path(tempfile.gettempdir()) / "foodland-ai-agent" / ...`
   rather than sharing one constant — a single `FOODLAND_DATA_DIR` resolver
   removes this duplication as a side effect.
6. No `/admin/*` endpoint currently calls `set_active_ranking_profile_version()`
   or `approve_and_activate()` — promotion is not reachable from any live HTTP
   path today, independent of the durability question. (Addressed in Part C.)
