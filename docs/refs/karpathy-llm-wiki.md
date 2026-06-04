# Karpathy — "LLM Wiki" (참조 원문)

출처: gist `karpathy/442a6bf555914893e9891c11519de94f` (`llm-wiki.md`, 2개월 전).
이 컨테이너는 네트워크 allowlist로 원격을 못 읽어, 본문을 보존용으로 복사해 둔다.
(댓글 수십 개의 구현체 목록은 생략 — 본문 패턴만.)

---

## LLM Wiki
A pattern for building personal knowledge bases using LLMs.

This is an idea file, designed to be copy-pasted to your own LLM agent (Codex,
Claude Code, OpenCode/Pi, …). It communicates the high-level idea; the agent
builds out specifics with you.

### The core idea
Most LLM+document experience is **RAG**: upload files, retrieve chunks at query
time, generate an answer. The LLM rediscovers knowledge from scratch every
question — nothing accumulates.

The idea here is different: the LLM incrementally **builds and maintains a
persistent wiki** — structured, interlinked markdown between you and raw
sources. New source → the LLM reads it, extracts key info, integrates it
(updating entity pages, revising summaries, flagging contradictions,
strengthening/challenging the synthesis). Knowledge is **compiled once and kept
current**, not re-derived per query. The wiki is a **persistent, compounding
artifact**: cross-references already there, contradictions already flagged.

You (almost) never write the wiki — the LLM does. You curate sources, explore,
ask the right questions. The LLM does the grunt work (summarizing,
cross-referencing, filing, bookkeeping). In practice: LLM agent on one side,
Obsidian on the other. **Obsidian is the IDE; the LLM is the programmer; the
wiki is the codebase.**

Contexts: personal (goals/health/journal), research (weeks/months on a topic),
reading a book (companion fan-wiki), business/team internal wiki (Slack,
transcripts, docs), competitive analysis, due diligence, course notes…

### Architecture — three layers
1. **Raw sources** — curated source docs. **Immutable** — source of truth.
2. **The wiki** — LLM-generated markdown (summaries, entity/concept pages,
   comparisons, overview, synthesis). The **LLM owns this layer entirely**.
3. **The schema** — a doc (e.g. `CLAUDE.md`/`AGENTS.md`) telling the LLM how the
   wiki is structured, conventions, and workflows for ingest/query/maintain.
   The key config that makes it a disciplined maintainer, not a chatbot.
   Co-evolved over time.

### Operations
- **Ingest.** Drop a source → LLM reads it, discusses takeaways, writes a
  summary page, updates the index, updates relevant entity/concept pages, appends
  to the log. One source may touch 10–15 pages.
- **Query.** Ask against the wiki → LLM finds pages, synthesizes a cited answer
  (md page, table, slide deck, chart, canvas). **Good answers get filed back
  into the wiki as new pages** — explorations compound too.
- **Lint.** Periodic health-check: contradictions, stale claims, orphan pages,
  important concepts lacking a page, missing cross-references, data gaps. Suggest
  new questions/sources.

### Indexing and logging
- `index.md` — **content catalog**: every page with link + one-line summary,
  organized by category. LLM reads it first when answering. Works well at
  moderate scale (~100 sources, hundreds of pages) **without embedding RAG**.
- `log.md` — **chronological** append-only record (ingests, queries, lints).
  Consistent prefix (`## [2026-04-02] ingest | Title`) → grep-able.

### Optional: CLI tools
A search engine over wiki pages (e.g. `qmd` — local hybrid BM25/vector +
re-rank, CLI + MCP). At small scale the index file is enough.

### Tips
Obsidian Web Clipper (web→md), download images locally, graph view to see
shape/hubs/orphans, Marp slides, Dataview over frontmatter, **the wiki is just a
git repo of markdown** (version history, branching, collaboration for free).

### Why this works
The tedious part of a knowledge base is **bookkeeping** (cross-refs, summaries,
consistency). Humans abandon wikis because maintenance grows faster than value.
LLMs don't get bored and can touch 15 files in one pass — maintenance cost ≈ 0.
Human curates/directs/asks/thinks; LLM does everything else. Related in spirit
to **Vannevar Bush's Memex (1945)** — the part Bush couldn't solve (who
maintains it) is what the LLM handles.

### Note
Intentionally abstract — the idea, not an implementation. Directory structure,
schema, page formats, tooling all depend on your domain. Everything is optional
and modular. Share it with your agent and instantiate a version that fits.
