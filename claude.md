# Eventron — 会场智能排座 Multi-Agent 系统

Python 3.11+ / FastAPI + LangGraph / PostgreSQL + Redis / Docker

## Architecture (6-Layer, One-Way Dependency)

```
API Routes → Services → Repositories → Models
Agents → Tools → Services → Repositories → Models
```

Organizer Web Portal (JWT)

## Tech Stack — DO NOT DEVIATE

langgraph>=0.4, langchain-core>=0.3, langchain-openai/anthropic/deepseek, fastapi>=0.115, sqlalchemy 2.x + alembic, openpyxl, weasyprint, qrcode[pil], jinja2, pyjwt

**禁用:** Django, CrewAI/AutoGen, Flask, MongoDB, reportlab, pandas

## Directory Layout

```
app/models/          — SQLAlchemy ORM (Event, Attendee, Seat, ApprovalRequest, Organizer, BadgeTemplate)
app/repositories/    — All DB queries (BaseRepository + per-entity repos)
app/services/        — Business logic (event, seating, checkin, approval, auth, identity, session, dashboard, import, attendee, badge_template)
app/schemas/         — Pydantic v2 request/response
app/api/             — Thin routes (events, seats, attendees, approvals, auth, dashboard, import_attendees, badge_templates, export, event_files, agent_chat)
app/deps.py          — FastAPI Depends() DI wiring
agents/              — LangGraph multi-agent (state.py, graph.py, orchestrator.py, registry.py)
agents/plugins/      — Pluggable sub-agents (base.py, planner, organizer, identity, seating, checkin, change, pagegen, badge, guide)
tools/               — Pure functions (seating_engine, excel_io, qr_gen, badge_render, seat_visualizer, page_render, file_extract)
templates/           — Jinja2 (pages/ + badges/)
tests/unit/          — 176 tests passing (no DB, no network)
tests/integration/   — DB tests (testcontainers)
```

## Core Decoupling Rules

1. **Repos only** — All `session.execute()` in `app/repositories/`. No raw SQL elsewhere.
2. **Services own logic** — Services call repos. Never touch Request/Response/LangGraph state.
3. **Routes are thin** — Validate → call service → return response. Zero logic.
4. **Agents call services** — Plugins never do DB queries directly.
5. **Tools are pure** — No DB, no HTTP, no state. Agent fetches data first, passes plain dicts.

Import rules: models→nothing | repos→models | services→repos | api→services,schemas | agents→services,tools | tools→stdlib only

## Data Models (key fields)

**Event:** name, event_date, location, venue_rows/cols, layout_type(theater|classroom|roundtable|banquet|u_shape), status(draft|active|completed|cancelled), config(JSONB)
- Transitions: draft→{active,cancelled}, active→{completed,cancelled}, cancelled→{draft}, completed→{}

**Attendee:** event_id(FK), name, title, organization, department, role(free-text, e.g. "甲方嘉宾"/"演讲嘉宾"/"工作人员"/"参会者"), priority(int 0-100, higher=more important, used for seating), phone, email, attrs(JSONB), wecom_user_id, lark_user_id, status(pending|confirmed|checked_in|absent|cancelled)
- `role` is a free-text label (no enum). Default "参会者".
- `priority` drives seat assignment algorithms (front row, zone matching).
- `attrs` JSONB = escape hatch. Never add columns for one-off attributes.

**Seat:** event_id(FK), row_num, col_num, label, seat_type(normal|reserved|disabled|aisle), zone(nullable String, e.g. "贵宾区"/"嘉宾区"), pos_x(Float, canvas units), pos_y(Float, canvas units), rotation(Float, degrees), area_id(FK nullable→VenueArea), attendee_id(FK). UniqueConstraint(event_id, area_id, row_num, col_num). Free-form layouts use pos_x/pos_y for arbitrary positioning (roundtable circles, U-shape, theater arcs).

**ApprovalRequest:** event_id, requester_id, change_type(swap|add_person|remove|reassign|bulk_change), change_detail(JSONB), status(pending|approved|rejected|expired), lg_thread_id

**Organizer:** email(unique), password_hash(PBKDF2-SHA256), name, phone, role(admin|member), is_active

**BadgeTemplate:** name, template_type(badge|tent_card), html_template, css, is_builtin, style_category(business|academic|government|custom)

## Agent Plugin System

Every sub-agent extends `AgentPlugin` ABC: name, description, intent_keywords, tools, handle(state), requires_identity, enabled, llm_model.
Plugins receive a `services` dict at construction: `{event, seating, attendee, llm_factory}`.
Base class provides `self.event_svc`, `self.seat_svc`, `self.attendee_svc`, `self.get_llm(tier)`.
`PluginRegistry` — register/get/active_plugins/build_routing_prompt(). Orchestrator NEVER hard-codes plugin names.

**AgentState:** messages, current_plugin, user_profile, event_id, pending_approval, turn_output, plan_output, attachments, task_plan, parts, reflection
**Graph (v2 — tool-calling routing):** orchestrator_agent (ReAct loop) → reflect → END. Orchestrator is a ReAct agent whose tools include `delegate_to_{plugin}` (one per active plugin) + utility tools (list_events, describe_capabilities). Multi-step orchestration (planner→organizer→seating) happens via sequential tool calls within one ReAct loop. No more continue_plan state machine or conditional edges.
**Delegate tools:** `agents/tools/routing_tools.py` — `make_delegate_tools()` wraps each plugin.handle() as a LangChain tool. Captures state side-effects (event_id, tool_calls, parts) via mutable accumulator closures. Scope filtering: when scope="seating", only delegate_to_seating exposed.
**Nested ReAct:** Orchestrator ReAct loop calls delegate_to_seating → inside that tool, SeatingPlugin runs its own ReAct loop with seating-specific tools. Outer loop handles routing, inner loops handle domain execution. Same pattern as Claude Code / OpenAI Agents SDK.
**Identity gate:** Pre-check in orchestrator_agent_node before ReAct loop. If user_profile is None and plugins need identity, runs identity plugin first.
**HITL:** Change plugin uses quick_replies for approval flow (interrupt() planned but not active).

**LLM Tiers:** fast(deepseek)=orchestrator/identity/checkin/badge/guide, smart(gpt-4o)=organizer/seating/change/planner-planning, strong(claude-sonnet)=planner-vision/pagegen-ReAct, max(claude-opus)=pagegen-internal-generation(deploy_custom_checkin_page内部LLM调用，16K tokens)

**9 Plugins (all LLM-first):** identity(LLM name extraction+heuristic fallback), planner(multimodal+task decomposition, Excel via read_excel_sheets_as_text→LLM), organizer(event CRUD+capacity calc), **seating(ReAct tool-calling agent: 14 LangChain tools via bind_tools+react_loop)**, checkin, change(LLM classifies change type+extracts details, HITL), badge(LLM sub-intent routing), **pagegen(ReAct agent: 11 tools, "vibe coding" — deploy_custom takes short description, internal max-tier LLM generates complete HTML page with CSS inline)**, guide
**agent_chat.py** now uses real LangGraph: `build_graph()` → `graph.ainvoke()` with service-injected plugins.
**Multimodal input:** agent_chat accepts multipart form data (images/Excel/PDF), planner uses vision LLM to extract event info.
**File processing tools:** `tools/file_extract.py` — build_vision_message, extract_from_excel, extract_from_pdf, detect_file_type. `tools/excel_io.py` — read_excel_sheets_as_text (raw text for LLM), **parse_seat_layout_structured** (spatial Excel parser: extracts areas, attendee positions, aisles, stage, roles from sheet names; returns structured dict). `tools/event_files.py` — pure filesystem helpers (load_manifest, find_files_by_type, find_latest_file_by_type) for reading event file store. `tools/chinese_norm.py` — **T→S normalization** for event domain terms (normalize_event_term, normalize_role, normalize_zone, infer_role_from_area_name, clean_name). Curated char/word mapping, never touches personal names.
**File persistence:** agent_chat uploads are persisted to `event_files` API (`uploads/events/{event_id}/`), not temp dir.
**Event file access:** Base `AgentPlugin.get_event_files(event_id, file_type)` lets any plugin look up previously uploaded files. Seating and planner plugins auto-detect when user references files without current attachment and fall back to event file store.
**Multimodal messages:** `_build_multimodal_message()` embeds images as base64 data URIs in `HumanMessage(content=[...])`. `extract_text_content()` in `agents/llm_utils.py` safely extracts text from both string and multimodal content formats — used by all plugins and orchestrator.
**Duplicate file handling:** Both `agent_chat.py` and `event_files.py` replace old manifest entries when uploading a file with the same original filename (old disk file also deleted).
**Utility tools in orchestrator:** `agents/tools/general_tools.py` (list_events, get_event_detail, get_event_summary, describe_capabilities) are directly available in the orchestrator's ReAct loop alongside delegate tools. No separate chat_fallback_node needed.
**Chat history persistence:** Frontend uses sessionStorage. AssistantPage: single key `eventron_assistant_chat`. SubAgentPanel: per event+scope key `eventron_sub_{eventId}_{scope}`. Survives page navigation, cleared on explicit "清空" or session end.

### Agent Self-Evolution System

Three-layer closed-loop self-optimization, all under `agents/`:

**Layer 1 — Reflection (`reflection.py`):** Post-execution self-check. Domain-specific validators for seating (utilization rate, unseated attendees, zone coverage) and badge (tool call verification, PDF link check). Generic validator checks reply quality and error rate. `deep_reflect()` uses LLM for complex quality assessment. Runs as `reflect` node in graph after every plugin.

**Layer 2 — Event Memory (`memory.py`):** Per-event interaction logs stored as JSON under `data/agent_memory/{event_id}/`. Each `InteractionRecord` captures: plugin, user_msg, agent_reply, tool_calls, reflection_score, user_feedback(+1/-1). `get_relevant_experiences()` retrieves past successful interactions for context injection. `find_similar_event_experiences()` searches across events by layout_type/attendee_count similarity.

**Layer 3 — Prompt Evolution (`prompt_evolution.py`):** Versioned system prompts per plugin under `data/prompt_versions/{plugin}/`. `PromptVersion` tracks: uses, avg_score, feedback counts, A/B ratio. `PluginPromptManager.get_active_prompt()` routes traffic between baseline and candidates. `evaluate_candidates()` auto-promotes winners (score > baseline + 0.1) and drops losers. `generate_improved_prompt()` uses LLM to create new variants from failure analysis.

**Graph integration:** `orchestrator_agent → reflect → END`. Reflect node: validate result → record to memory → update prompt scores. Experience injection: inside delegate tools, `_experiences` injected from memory before each plugin.handle().
**Frontend:** 👍👎 buttons on AI messages (via `FeedbackButtons` in ChatMessage), reflection quality bar. `POST /agent/chat/feedback` records to memory. `GET /agent/chat/stats/{event_id}` returns aggregated stats.

### Agent Design Principle — Tool-Calling ReAct Agents

**Core rule:** Agents use LangChain `bind_tools()` + ReAct loop. LLM decides WHEN and WHICH tools to call. No hardcoded keyword routing.

**Architecture (seating plugin as reference):**
1. `agents/tools/seating_tools.py` — `make_seating_tools(event_id, seat_svc, event_svc, attendee_svc)` factory. 10 `@tool` functions wrapping service calls via closure.
2. `agents/react.py` — `react_loop(llm, messages, tools, max_iter=10)`. Generic ReAct loop: LLM thinks → calls tools → observes results → iterates → final text response.
3. `agents/plugins/seating.py` — `SeatingPlugin.handle()` builds tools → `llm.bind_tools(tools)` → `react_loop()`.

**Pattern for every tool-calling plugin:**
1. Create `agents/tools/{name}_tools.py` with `make_{name}_tools()` factory
2. Each tool is a thin async wrapper around a service method, decorated with `@tool`
3. Plugin `handle()`: build tools → bind to LLM → run `react_loop()` → return result
4. System prompt tells LLM its capabilities and workflow rules (e.g. "verify after each operation")

### Structured Message Parts Protocol

Tools can return structured UI card data alongside text responses. The frontend renders each card type with a dedicated React component.

**Protocol:** `agents/message_parts.py` defines part constructors: `seat_map_part`, `attendee_table_part`, `event_card_part`, `page_preview_part`, `confirmation_part`, `file_link_part`, `stats_part`.
**Accumulator:** `PARTS_ACCUMULATOR` (contextvars) lets any tool push parts without changing return types. Set by orchestrator before ReAct loop.
**API:** `ChatResponse.parts: list[dict] | None`. SSE `done` event includes `parts` field.
**Frontend:** `MessagePartCards.tsx` — dispatcher component `MessagePartCard` maps type → React component. `MessageParts` renders a list. Integrated into `ChatMessage.tsx` between tool calls and quick replies.
**Card types:** seat_map (layout stats + zones + progress bar), attendee_table (scrollable roster), event_card (summary with status badge), page_preview (iframe), confirmation (action buttons), file_link (download badge), stats (KV grid).

**Why ReAct over hardcoded routing:**
- LLM handles messy inputs (merged cells, mixed languages, vague user intent) that regex/heuristics cannot
- LLM chains multiple tools autonomously (read Excel → import attendees → create layout → set zones → verify)
- Self-verification: LLM calls `view_seats` after layout creation to confirm results
- Tools stay pure (structured input → structured output), all intelligence lives in the LLM layer

**Seating tools (20):** get_event_info, view_seats, create_layout, create_custom_layout, auto_assign, set_zone, set_zone_unzoned, read_event_excel, **analyze_seat_chart**(structured Excel parser→areas/positions/roles), **import_from_seat_chart**(one-click: create areas+import attendees+layout+assign), list_attendees, import_attendees, list_attendees_with_seats, swap_two_attendees, reassign_attendee_seat, unassign_attendee, list_areas, create_area, generate_area_layout, delete_area

**Other plugins (LLM-first JSON, not yet tool-calling):** identity, change, badge, pagegen use `extract_json()` from `agents/llm_utils.py` for robust LLM JSON parsing (3-layer: direct → code block → embedded).

## Organizer Portal (Phase A — Done)

JWT auth (AuthService), separate from IM identity. Routes under `/api/v1/`:
- auth: register/login/me
- dashboard: event stats aggregation
- import: Excel preview + confirm (auto-map columns, detect duplicates)
- badge-templates: CRUD (built-in templates immutable)
- events: full CRUD + duplicate + state transitions
- attendees: full CRUD + checkin + stats

**Phase B (in progress):** 文件管理, 铭牌设计(模板+AI), 签到页设计(H5+AI), 子Agent面板
**Phase C (next):** 座位图拖拽编辑器, 签到实时看板(WebSocket), 审批中心, 团队协作

## Coding Rules

- Type hints everywhere. `X | None` not `Optional[X]`. Async by default.
- Pydantic v2, f-strings, pathlib.Path, Google-style docstrings, 100-char lines.
- Services raise domain exceptions (exceptions.py). Routes catch → HTTP codes. Agents → friendly fallback.
- All DI via `Depends()`. Never construct repos/services inline.
- Test-first: schema → failing test → implement → integration test → full suite.
- Coverage: tools≥95%, services≥90%, repos≥85%, agents≥80%, api≥75%.
- Mock rules: AsyncMock for repos in service tests, never call real LLM, use FakeClass (not AsyncMock(name=...)) for objects with `.name` attribute.

## Exceptions (app/services/exceptions.py)

EventronError → NotFoundError(Event/Attendee/Seat/Template) | SeatNotAvailableError | InvalidStateTransitionError | DuplicateAssignmentError | ApprovalRequiredError | AuthenticationError | DuplicateEmailError

## Test Status

234 unit tests passing. Files: test_seating_engine(26), test_excel_io(10), test_schemas(26), test_services(19), test_event_service(41), test_attendee_service(15), test_badge_template_service(13), test_auth_service(15), test_identity_service(13), test_import_service(14), test_dashboard_service(3), test_chinese_norm(24), test_seat_layout_parser(16). Skipped: test_qr_gen (missing qrcode dep in dev env).

## Implementation Phases

### Done ✅
- **Phase 0** — Project skeleton (pyproject, config, docker-compose, Makefile, conftest)
- **Phase 1** — Data layer (all ORM models, repos with CRUD, Pydantic schemas)
- **Phase 2** — Core tools (seating_engine 3 algorithms, excel_io import/export, qr_gen)
- **Phase 3** — Service layer (event, seating, checkin, approval services)
- **Phase 4** — REST API (all CRUD routes, deps.py DI, Swagger UI)
- **Phase 5** — Agent core (state, registry, orchestrator intent routing, graph compile)
- **Phase 6** — Agent plugins (identity→seating→checkin→change→badge→pagegen→guide)
- **Phase A (Portal)** — Organizer web portal backend:
  - Models: Organizer, BadgeTemplate
  - Services: auth(JWT/PBKDF2), identity, session(Redis), dashboard, import(Excel), attendee, badge_template
  - API v1: auth, dashboard, import, badge-templates, events CRUD+duplicate, attendees full CRUD+checkin

- **Phase 8** — H5 pages + badges:
  - tools: badge_render(Jinja2+WeasyPrint, business/tent_card/conference templates), page_render(H5 checkin page)
  - API: /export/badges/html (browser print), /export/badges/preview (event-scoped), /badge-templates/preview (standalone, no eventId)
  - AgentState.scope for forced plugin routing from SubAgentPanel
  - BadgeTab: template gallery with iframe previews + HTML generate/print buttons (3 built-in types: conference/business/tent_card)
  - Badge plugin: ReAct tool-calling agent with `design_template` (full HTML+CSS), `generate_badges` (HTML output)
  - **Conference template** (NEW): 90×130mm vertical, deep blue gradient, SVG cityscape, white name band, glow effects (`templates/badges/conference.html/css`)
  - **BadgeTemplatesPage**: iframe-based visual previews (built-in + custom), preview modal, standalone preview endpoint
  - **SubAgentPanel file picker**: popover showing existing event files + upload-new option (replaces direct file dialog)
  - **Image MIME detection**: magic-bytes based detection in `agent_chat.py` and `file_extract.py` (fixes WeChat .jpg→PNG mismatch)
  - **LLM config**: `max_tokens` 2000→4096, model `claude-sonnet-4-6`

- **Phase 9** — Priority-based roles + venue zones + seat map editor:
  - **Role refactor:** Replaced fixed role enum (vip/speaker/organizer/staff/attendee) with free-text `role` + `priority` (int 0-100). Labels customizable (甲方嘉宾, 演讲嘉宾, 工作人员, etc.).
  - **Venue zones:** Added `seat.zone` (nullable string, e.g. "贵宾区", "嘉宾区"). Zone-aware seating algorithms.
  - **Seating algorithms:** priority_first, by_zone, by_department (all priority-based), random, legacy vip_first (compat).
  - **AI zone suggestion:** `suggest_zones()` pure heuristic + `GET /seats/suggest-zones` API endpoint.
  - **Seat map editor:** Zone painting (click-to-paint seats into zones), AI auto-zone, zone legend, priority-based seat colors.
  - **Frontend updates:** AddAttendeeModal (role presets + priority slider), AttendeesTab (priority-based badges), SeatingTab (zone painting + AI suggestions + SubAgentPanel).
  - **Migration:** `c3a7d8e2f195` — adds attendee.priority, seat.zone, migrates old role values + vip seat_type.
  - API: `PATCH /seats/{seat_id}` (update zone/type), `GET /seats/suggest-zones` (AI zone suggestions).

- **Phase 10** — Free-form layouts + SVG seat map editor:
  - **Seat model:** Added `pos_x`, `pos_y` (Float) and `rotation` (Float) for free-form positioning.
  - **Layout generators:** 6 layout types in `seating_engine.generate_layout()`: grid, theater (curved arcs), classroom (paired desks), roundtable (circular tables), banquet (long tables), u_shape (3-sided).
  - **SVG canvas editor:** Replaced CSS grid with SVG-based seat map. Pan (drag/middle-click), zoom (scroll wheel), tool modes (select/pan).
  - **Drag-to-select zone painting:** Rubber-band box selection → bulk zone update. Replaces click-one-at-a-time.
  - **Bulk update API:** `PATCH /seats/bulk` with `BulkSeatUpdate` schema (seat_ids + zone/type). Single DB round-trip via `UPDATE ... WHERE id IN (...)`.
  - **Layout creation API:** `POST /seats/layout` with `LayoutRequest` schema (layout_type, rows, cols, table_size, spacing). Replaces old grid-only creation.
  - **Migration:** `d4f8a1b2c396` — adds pos_x, pos_y, rotation; back-fills from row_num/col_num.

- **Phase 11** — Public check-in system (scan QR → mobile H5 → search name → check in):
  - **Public API** (`app/api/public_checkin.py`): NO-JWT routes under `/p/{event_id}/checkin`. Endpoints: `GET /checkin` (serve H5 page), `POST /checkin/search` (name search), `POST /checkin/confirm/{aid}` (confirm), `GET /checkin/stats` (live stats).
  - **H5 template** (`templates/pages/checkin.html/css/js`): Mobile-first interactive page. Deep blue gradient, name search → disambiguation → check-in confirm → success + seat info. Self-contained JS calls public API via fetch. Stats poll every 15s.
  - **Agent tools** (`agents/tools/checkin_tools.py`): 11 LangChain tools via `make_checkin_tools(event_id, checkin_svc, event_svc, attendee_svc, llm)`. `deploy_custom_checkin_page(design_description)` takes a SHORT text description and internally calls the LLM to generate HTML+CSS (avoids LLM cramming thousands of chars into tool args). Other tools: `get_event_info`, `get_checkin_stats`, `get_checkin_url`, `generate_checkin_qr`, `render_checkin_page`, `list_attendee_roles`, `preview_checkin_page`, `get_current_page_source`, `patch_page_css`, `update_page_source`.
  - **Pagegen plugin ("vibe coding")**: ReAct agent where tools provide data and lightweight actions. Heavy page generation happens INSIDE `deploy_custom_checkin_page` via an internal LLM call. 3-level edit: `patch_page_css` (CSS-only) → `get_current_page_source` + `update_page_source` (read-modify-write) → `deploy_custom_checkin_page(description)` (full AI redesign).
  - **react_loop upgrade**: Consecutive failure detection — same tool failing 2+ times triggers abort + user-facing error message. Progress callback via PROGRESS_QUEUE contextvars for SSE streaming.
  - **Service wiring**: CheckinService injected into agent_chat services dict (`"checkin"` key). Both chat endpoints updated.
  - **CheckinDesignTab**: Phone frame iframe preview of live check-in page, copy link button, external open, stats with auto-refresh, SubAgentPanel scope="pagegen".
  - **Vite proxy**: Added `/p` proxy to backend for dev mode.
  - **page_render.py**: Added `event_id` param + `_load_js()` for inline JS injection.

- **Phase 12** — Agent config system (runtime prompt/model editing):
  - **Service**: `app/services/agent_config_service.py` — JSON-file-backed config store under `data/agent_config.json`. Defaults registered at startup from each plugin's hardcoded constants. Read/write with asyncio lock. Helpers: `get_effective_prompt()`, `get_effective_tier()`, `get_effective_gen_tier()`.
  - **API**: `app/api/agent_config.py` — `GET /agent-config` (list all), `GET /agent-config/{name}` (detail), `PATCH /agent-config/{name}` (partial update), `POST /agent-config/{name}/reset` (revert to defaults).
  - **Plugin wiring**: `AgentPlugin._effective_prompt(default)` and `_effective_tier()` in base class. All 7 plugins with system prompts + orchestrator updated to call these. Pagegen uses `get_effective_gen_tier()` for internal LLM.
  - **Frontend**: `AgentSettingsPage` — card-based UI per plugin with expand/collapse, model tier selector (fast/smart/strong/max), system prompt textarea editor, enabled toggle, save/reset. Route `/agent-settings`, sidebar nav entry.

- **Phase 13** — Multi-area venue support (VenueArea):
  - **VenueArea model** (`app/models/venue_area.py`): One Event → many Areas. Fields: name, layout_type, rows, cols, display_order, offset_x, offset_y, stage_label. Cascade delete-orphan from Event.
  - **Seat.area_id**: Optional FK to venue_areas. UniqueConstraint changed from `(event_id, row_num, col_num)` to `(event_id, area_id, row_num, col_num)` so different areas can share row/col numbers.
  - **Repository**: `VenueAreaRepository` with `get_by_event()` ordered by display_order. `SeatRepository.delete_by_area()` for area-scoped seat deletion.
  - **Service**: `SeatingService` extended with area CRUD + `generate_area_layout()` — deletes area-specific seats then recreates with offset positioning.
  - **API**: `app/api/venue_areas.py` — CRUD routes under `/{event_id}/areas` + `POST /{area_id}/generate-layout`.
  - **Schemas**: VenueAreaCreate, VenueAreaUpdate, VenueAreaResponse, VenueAreaWithSeats. SeatResponse gains `area_id`.
  - **Agent tools**: 4 new seating tools (list_areas, create_area, generate_area_layout, delete_area). System prompt updated with multi-area workflow. max_iter 10→15.
  - **Agent workflow enforcement**: System prompt rewritten with "核心原则：操作必须完成全流程" — read Excel → import attendees → create layout → set zones → auto_assign → view_seats verify.
  - **Graceful overflow**: All 4 assignment algorithms changed from ValueError to partial assignment when attendees > seats.
  - **Frontend**: SeatingTab gains area management panel (create/delete/regenerate areas), SVG area boundary rects with dashed borders, area name labels, per-area stage bars.
  - **Migrations**: `e5a2b3c4d507` (create venue_areas table + seats.area_id FK), `f7c3d8e9a012` (fix unique constraint to include area_id).

### Next 🔜
- **Phase B (Portal)** — 物料计算与物料管理(按活动规模自动估算+手动调整), 铭牌设计(模板管理收进badge agent+活动内BadgeTab，外层菜单降级admin-only), 签到实时看板(WebSocket), 审批中心
- **Phase C (Portal)** — 团队协作(多Organizer), 自动审批规则引擎

## Quickstart

```bash
pip install -e ".[dev]"
cp .env.example .env  # fill LLM keys
make up               # docker compose postgres + redis
alembic upgrade head && python scripts/seed.py
make all              # docker compose up --build
```

## Git

Repo: https://github.com/AntiNoise-ai/Eventron (Apache 2.0)
Push: `git remote set-url origin https://AntiNoise-ai:<PAT>@github.com/AntiNoise-ai/Eventron.git && git push`
PAT 存本地，不入库。推完后 `git remote set-url origin https://github.com/AntiNoise-ai/Eventron.git` 清掉 token。

## Don'ts

No business logic in routes. No interrupt() outside change plugin. No sync DB drivers. No hardcoded plugin names. No LLM responses in DB. No attrs columns for one-offs. No skipping tests. No agents→DB directly. No circular imports.
