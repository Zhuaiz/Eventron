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

**Seat:** event_id(FK), row_num, col_num, label, seat_type(normal|reserved|disabled|aisle), zone(nullable String, e.g. "贵宾区"/"嘉宾区"), attendee_id(FK). UniqueConstraint(event_id, row_num, col_num).

**ApprovalRequest:** event_id, requester_id, change_type(swap|add_person|remove|reassign|bulk_change), change_detail(JSONB), status(pending|approved|rejected|expired), lg_thread_id

**Organizer:** email(unique), password_hash(PBKDF2-SHA256), name, phone, role(admin|member), is_active

**BadgeTemplate:** name, template_type(badge|tent_card), html_template, css, is_builtin, style_category(business|academic|government|custom)

## Agent Plugin System

Every sub-agent extends `AgentPlugin` ABC: name, description, intent_keywords, tools, handle(state), requires_identity, enabled, llm_model.
Plugins receive a `services` dict at construction: `{event, seating, attendee, llm_factory}`.
Base class provides `self.event_svc`, `self.seat_svc`, `self.attendee_svc`, `self.get_llm(tier)`.
`PluginRegistry` — register/get/active_plugins/build_routing_prompt(). Orchestrator NEVER hard-codes plugin names.

**AgentState:** messages, current_plugin, user_profile, event_id, pending_approval, turn_output, attachments, task_plan
**Graph:** orchestrator → conditional edge → plugin → orchestrator → END (when turn_output set)
**Plan-and-Execute:** attachments present → planner → task decomposition → user confirms → plugins execute
**HITL:** Only `change` plugin uses `interrupt()`. PostgresSaver in prod, MemorySaver in tests.

**LLM Tiers:** fast(deepseek)=orchestrator/identity/checkin/badge/guide, smart(gpt-4o-mini)=organizer/seating/change/planner-planning, strong(claude-sonnet)=planner-vision/pagegen

**9 Plugins:** identity, planner(multimodal+task decomposition), organizer(event CRUD+capacity calc), seating, checkin, change(HITL), badge, pagegen, guide
**agent_chat.py** now uses real LangGraph: `build_graph()` → `graph.ainvoke()` with service-injected plugins.
**Multimodal input:** agent_chat accepts multipart form data (images/Excel/PDF), planner uses vision LLM to extract event info.
**File processing tools:** `tools/file_extract.py` — build_vision_message, extract_from_excel, extract_from_pdf, detect_file_type.

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

179 unit tests passing. Files: test_seating_engine(17), test_excel_io(10), test_schemas(19), test_services(19), test_event_service(41), test_attendee_service(15), test_badge_template_service(13), test_auth_service(15), test_identity_service(13), test_import_service(14), test_dashboard_service(3). Skipped: test_qr_gen (missing qrcode dep in dev env).

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
  - tools: badge_render(Jinja2+WeasyPrint, business/tent_card templates), page_render(H5 checkin page)
  - API: /export/badges PDF endpoint, scope-routed agent chat
  - AgentState.scope for forced plugin routing from SubAgentPanel
  - BadgeTab: template gallery + PDF generate buttons
  - Badge plugin: sub-intent routing (generate/list/design)

- **Phase 9** — Priority-based roles + venue zones + seat map editor:
  - **Role refactor:** Replaced fixed role enum (vip/speaker/organizer/staff/attendee) with free-text `role` + `priority` (int 0-100). Labels customizable (甲方嘉宾, 演讲嘉宾, 工作人员, etc.).
  - **Venue zones:** Added `seat.zone` (nullable string, e.g. "贵宾区", "嘉宾区"). Zone-aware seating algorithms.
  - **Seating algorithms:** priority_first, by_zone, by_department (all priority-based), random, legacy vip_first (compat).
  - **AI zone suggestion:** `suggest_zones()` pure heuristic + `GET /seats/suggest-zones` API endpoint.
  - **Seat map editor:** Zone painting (click-to-paint seats into zones), AI auto-zone, zone legend, priority-based seat colors.
  - **Frontend updates:** AddAttendeeModal (role presets + priority slider), AttendeesTab (priority-based badges), SeatingTab (zone painting + AI suggestions + SubAgentPanel).
  - **Migration:** `c3a7d8e2f195` — adds attendee.priority, seat.zone, migrates old role values + vip seat_type.
  - API: `PATCH /seats/{seat_id}` (update zone/type), `GET /seats/suggest-zones` (AI zone suggestions).

### Next 🔜
- **Phase B (Portal)** — 物料计算与物料管理(按活动规模自动估算+手动调整), 铭牌设计(模板管理收进badge agent+活动内BadgeTab，外层菜单降级admin-only), 签到页设计(H5+AI), 子Agent面板, 签到实时看板(WebSocket), 审批中心
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

Repo: https://github.com/Zhuaiz/Eventron (Apache 2.0)
Push: `git remote set-url origin https://Zhuaiz:<PAT>@github.com/Zhuaiz/Eventron.git && git push`
PAT 存本地，不入库。推完后 `git remote set-url origin https://github.com/Zhuaiz/Eventron.git` 清掉 token。

## Don'ts

No business logic in routes. No interrupt() outside change plugin. No sync DB drivers. No hardcoded plugin names. No LLM responses in DB. No attrs columns for one-offs. No skipping tests. No agents→DB directly. No circular imports.
