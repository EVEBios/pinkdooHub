# Development Changelog

> 每个独立功能模块完成后更新。记录做了什么、为什么这样做、有什么限制。

---

## v0.5.0 (Unreleased) — Order Module Final Review (Phase 4.2.12)

**Date:** 2026-08-13

### Summary

Completed the final architecture, security, transaction, query-performance, migration, test, and documentation review for Order v1.0. Phase 4.2 is code-complete and release-ready as the unreleased v0.5.0 candidate; Phase 4.3 Inventory is the next business stage.

### Reviewed and Changed

- Reviewed all nine HTTP operations against the frozen Order requirements/API contracts and verified API → Service → Repository → Model dependency direction, authenticated identity ownership, unified envelopes, and explicit user/admin response projection.
- Reviewed creation and state-change transaction boundaries, post-lock state validation, sequential audit writes, rollback injection, order-number collision attribution/retry, stable pagination ordering, batch Product/Option loading, database item counts, and preloaded detail relations.
- Reviewed `1_20260813130455_add_order_tables.py` as a MySQL 8+ additive migration: it creates only `orders` and `order_items`, preserves four historical `RESTRICT` foreign keys and five query indexes, declares the non-transactional DDL boundary, and contains no upgrade-side destructive SQL.
- Added a cross-module amount-capacity invariant proving the maximum legal request (`10 × 99 × 99999.00`) remains below `DECIMAL(10,2)` Order capacity. This documents why no additional total-overflow business error is necessary while the existing Product price and Order item bounds remain unchanged.
- Hardened shared audit IP extraction: only valid, length-safe IPv4/IPv6 literals are persisted; malformed, overlong, or IPv6 scope-bearing `X-Forwarded-For` values fall back to the direct peer, and an invalid/missing peer becomes `unknown`. A real Order HTTP test proves hostile proxy text cannot turn an otherwise valid audited mutation into a 500 or partial write.
- Advanced the unreleased application candidate from v0.4.0 to v0.5.0 in code defaults, example environment, version contracts, README, project instructions, architecture context, and Order requirement/API status. Advanced the database design document to v1.4 for the Order table addition.

### Important Decisions

1. **Release candidate, not a release:** v0.5.0 identifies the completed local code candidate. No Git tag, GitHub Release, commit, push, MySQL migration execution, Aerich fake, or development-database rebuild is implied.
2. **Aggregate constraints are reviewed together:** individual price, item-count, and quantity limits form a safe maximum total. A regression invariant now alerts future maintainers if any one bound changes enough to exceed storage capacity.
3. **Proxy input remains a trust boundary:** syntax and storage safety are enforced in the application, while deployment must still configure the ingress proxy to overwrite untrusted forwarding headers.
4. **Inventory remains out of scope:** Order continues to reject every Kit item before writes and never reads, deducts, or restores `ProductKit.stock`; those concurrency semantics belong to Phase 4.3.
5. **Migration execution is separately authorized:** the reviewed Order migration remains offline and unapplied. Production rollout still requires target-schema audit, backup/snapshot, staging verification, explicit authorization, and a tested rollback plan.

### Verification

- All 392 Order-related tests pass, including contracts, Models, migration DDL, Repository, Service, Mapper, routes, real JWT/SQLite HTTP flows, transaction rollback, and amount-capacity invariants.
- Six focused request-IP tests pass, plus the real Order audit integration regression.
- The complete project suite passes with 1178 tests.
- `compileall`, dependency integrity (`pip check`), and whitespace/error-marker review (`git diff --check`) pass.
- Ruff was not run because it is not installed in the project environment or declared in `requirements.txt`.

### Release Notes

- No dependency was added.
- The MySQL initial migration and Order incremental migration remain unapplied; the local development database was not rebuilt or mutated.
- `docs/02_database/er_diagram.png` remains an untracked user-owned artifact and was not modified.

---

## Unreleased — Order HTTP Error and Boundary Matrix (Phase 4.2.11)

**Date:** 2026-08-13

### Summary

Completed the full real-JWT/SQLite HTTP error and boundary matrix for all nine Order endpoints. The matrix now verifies authoritative Experience snapshots and Decimal totals, request-shape anti-forgery, Product/Option/Kit rejection, visibility and ADMIN+ permissions, pagination and combined filters, every illegal state precondition, ordered audit history, transactional failure rollback, and order-number collision retry behavior.

### Added

- Real HTTP creation coverage for multiple distinct Options, exact Decimal arithmetic, immutable historical snapshots, 1/99 quantity bounds, 500-character remarks, empty-remark normalization, duplicate/empty/oversized item collections, strict scalar types, and all server-owned field forgery attempts.
- Product and Option availability cases for missing, draft/offline/deleted, missing/deleted/mismatched Option, plus explicit Kit rejection with unchanged `ProductKit.stock` and no partial Order/audit writes.
- Full authentication and ADMIN+ route matrices, uniform missing-order/resource-hiding 404 behavior, user/admin list visibility, pagination, exact lookup, status/user/time combined filters, UTC/range validation, and reverse-chronological audit pagination.
- All nine illegal status-operation preconditions across cancel, mark-paid, and complete, with stable `40921` payloads and proof that neither status nor audit changes.
- HTTP-level fault injection after audit writes and at post-write reloads, proving atomic rollback of Order/Items/status/audit, plus collision retry success and third-collision exhaustion without partial artifacts.
- A shared transport dependency that rejects any non-empty request body on cancel/paid/complete while preserving body-free OpenAPI operations.

### Important Decisions

1. **Negative-space contracts are enforced:** omitting `requestBody` from OpenAPI is documentation, not runtime validation. The three fixed state-use-case PATCH routes now explicitly reject `{}`, `null`, or any other non-empty body with the unified HTTP 422 envelope before mutation.
2. **HTTP tests exercise real boundaries:** business-error and rollback cases use real JWT authentication, SQLite, repositories, services, mappers, and exception middleware. Dependency overrides are limited to deterministic generators and deliberate failure injection.
3. **Server authority is tested end to end:** authenticated identity, order status, Product/Option snapshots, unit prices, subtotals, and totals cannot be supplied by clients and remain frozen after source catalog changes.
4. **Failure responses disclose no internals:** injected runtime and database-integrity failures are logged server-side, return only the shared generic 500 envelope, and leave no partial aggregate or audit state.

### Verification

- 79 new focused HTTP matrix test instances pass across creation boundaries, query/permission/state behavior, and transaction/collision failure injection.
- Existing route architecture and mocked adaptation tests continue to pass with strict no-body enforcement and unchanged OpenAPI request-body declarations.
- 104 focused Order HTTP/route/architecture tests pass together; all 390 Order-related tests pass.
- The complete project suite passes with 1170 tests.

### Release Notes

- No dependency, database schema, migration, or application-version change was made in this step.
- The existing offline MySQL Order migration remains unapplied; no development database was rebuilt.
- Phase 4.2.12 final checklist, migration review, and version decision remain pending before declaring the Order module release-ready.

---

## Unreleased — Order FastAPI Routes (Phase 4.2.10)

**Date:** 2026-08-13

### Summary

Exposed the implemented Order domain through four authenticated user endpoints and five ADMIN+ endpoints. Added the Order composition root, strict request-to-domain adaptation, Mapper serialization, unified success/error envelopes, exact OpenAPI contracts, and core real JWT/SQLite HTTP lifecycle coverage. The exhaustive Phase 4.2.11 HTTP error/boundary matrix and Phase 4.2.12 final review remain pending.

### Added

- `get_order_service()` composition root wiring OrderRepository, ProductRepository, and the shared AuditLogService/AuditLogRepository.
- User routes for Experience creation, paginated own-order listing, owner-scoped detail, and Pending cancellation.
- ADMIN+ routes for filtered listing, unrestricted detail, manual payment confirmation, completion, and paginated Order audit history.
- Explicit OrderCreate-item to `OrderItemInput` adaptation so Service remains independent of transport Schemas.
- Authenticated identity as the sole source of `user_id`/`operator_id`, plus shared client-IP extraction for every audited HTTP mutation.
- Precise `SuccessResponse[T]` and shared `ErrorResponse` declarations, HTTP 201 creation, HTTP 200 queries/mutations, PATCH operations without request bodies, and one-time router registration tests.
- Real JWT/SQLite flows covering creation, Decimal snapshot response, user list, resource hiding, ADMIN+ access, paid/completed transitions, owner cancellation, ordered audits, source IPs, and audit privacy.
- Unified missing-Bearer handling through `AuthenticationException` by setting HTTPBearer `auto_error=False`; all routes using the existing authentication dependency now return the project error envelope for missing credentials.

### Important Decisions

1. **Composition root:** concrete repositories and shared infrastructure are assembled only in `app/api/deps.py`. Route modules import Service/Mapper/Schemas but never business repositories or Order/Product persistence models.
2. **Identity is server-owned:** create and owner-scoped routes use `current_user.id`; admin mutations use `current_admin.id`. Extra `user_id`, price, amount, or snapshot fields are rejected by strict request Schemas before Service execution.
3. **Authentication versus authorization:** missing credentials return HTTP 401 with the unified envelope, while an authenticated normal user accessing ADMIN+ routes returns HTTP 403. The pre-existing invalid/expired Token exception remains code `1006`/HTTP 400 pending a separate User-contract migration, so Order OpenAPI documents both 400 and 401.
4. **Single serialization pass:** routes call the dedicated Mapper and `model_dump(mode="json")`, then pass the validated data to `success()` with `response_model=None`; OpenAPI uses explicit generic response declarations without runtime Decimal revalidation.
5. **No body for state PATCH:** cancel, paid, and complete select fixed Service use cases entirely through the path and authenticated identity; clients cannot submit an arbitrary target state.

### Verification

- 25 focused Order route/architecture/integration test instances were added and pass after the unified-auth additions.
- 84 combined Order/User/Product route regressions pass after changing the shared HTTPBearer behavior.
- All 311 Order-related contracts pass together.
- Python compilation and dependency integrity checks pass; the complete suite passes with 1091 tests.

### Release Notes

- The nine documented Order endpoints are now registered and callable.
- No new dependency, database schema change, migration, or application-version change was made.
- The existing offline MySQL Order migration remains unapplied; no development database was rebuilt.
- Phase 4.2.11 must still expand the complete HTTP business-error/input-boundary matrix. Phase 4.2.12 must perform final checklist/migration/version review before declaring the Order module release-ready.

---

## Unreleased — Order API Mapper (Phase 4.2.9)

**Date:** 2026-08-13

### Summary

Implemented the synchronous Order API mapping boundary for user/admin lists, user/admin details, OrderItem snapshots, and lightweight status-transition responses. The Mapper performs explicit field projection and strict Out Schema validation without querying or mutating ORM aggregates. Dependency wiring and HTTP routes remain outside this slice.

### Added

- Authoritative OrderStatus and DayType `{value, label}` mapping using the existing common registries.
- Explicit OrderItem snapshot mapping with Decimal price/subtotal preservation and no live Product/Option reads.
- Separate user/admin list and detail projections; user responses never read User relations, while admin responses add only `user_id` and `user_nickname`.
- User/admin Page mapping that preserves total, page, page size, and pages while consuming Repository `item_count` annotations.
- Lightweight status-response mapping from a relation-free Order returned by the status transaction reload.
- Aggregate-integrity checks that reject an OrderItem attached to a different Order before serialization.
- Architecture, atomic conversion, projection, strict validation, real Repository zero-SQL, and non-mutation tests.

### Important Decisions

1. **Explicit projection:** each endpoint class has a dedicated mapper and Out Schema. Fields are assembled from a whitelist rather than passing ORM models directly to Pydantic, making user/admin isolation visible in code.
2. **Zero-SQL mapping:** lists consume the Repository's `item_count` annotation, details consume preloaded Items/User, and status responses consume a lightweight Order. Mapper functions contain no async code, Repository/Service imports, or ORM query calls.
3. **Snapshot-only items:** historical Item output uses the stored name, Option dimensions, day type, unit price, quantity, and subtotal. It never follows Product or ExperienceOption relationships that may have changed since purchase.
4. **Schema owns wire formatting:** Mapper preserves domain `Decimal` and Enum values; strict response Schemas validate arithmetic and serialize amounts as two-decimal strings. This avoids duplicating formatting rules in two layers.
5. **Non-mutating composition:** Mapper builds new dictionaries and Schema objects. Real aggregate snapshots prove the source Order, User, Items, relationship lists, and annotated fields are unchanged.

### Verification

- 23 focused Order Mapper tests pass.
- All 286 Order-related contracts pass together.
- The complete suite passes with 1066 tests after the Mapper and documentation updates.

### Release Notes

- No new dependency, database schema change, migration, endpoint, or application-version change is required.
- The existing offline Order migration remains unapplied; no development database was rebuilt.
- Order HTTP APIs remain unavailable until dependency composition and user/admin routes are implemented.

---

## Unreleased — Order Status Transition Service (Phase 4.2.8)

**Date:** 2026-08-13

### Summary

Implemented the three frozen Order state-transition use cases: owner cancellation, ADMIN+ manual payment confirmation, and ADMIN+ completion. Each use case locks the visible Order inside its transaction, validates the latest state, and atomically persists the status, audit, and lightweight response reload. Mapping, dependency wiring, and HTTP routes remain outside this slice.

### Added

- `OrderService.cancel_order()` for owner-scoped `pending → cancelled` with SQL-level visibility hiding.
- `OrderService.mark_order_paid()` for the temporary ADMIN+ `pending → paid` operational entry point.
- `OrderService.complete_order()` for ADMIN+ `paid → completed`.
- Stable `cancel`, `mark_paid`, and `complete` operation constants for `OrderStatusConflict` payloads.
- A private transition template that performs transaction-bound row locking, post-lock state validation, status persistence, sequential audit, and response reload without exposing a generic public status mutator.
- Unit and real SQLite tests for all success paths, status conflicts, missing/hidden resources, audit summaries, repeated-transition serial results, and audit/reload rollback.
- A static Repository contract proving `get_order_for_update()` retains `select_for_update()` for MySQL pessimistic locking semantics.

### Important Decisions

1. **Lock then decide:** state validity is checked only after `SELECT ... FOR UPDATE` returns the latest visible row. A pre-transaction read cannot authorize a mutation because another transaction may change the state before the write.
2. **Visibility in the lock query:** owner cancellation applies `(order_id, user_id)` before locking. Missing and foreign Orders therefore produce the same `40411 OrderNotFound`, without loading and revealing another user's row.
3. **No generic transition API:** callers select one of three named use cases and cannot supply an arbitrary target status. The private template receives only constants fixed by those public methods.
4. **Atomic status event:** status update, compact `before_status`/`after_status` audit, and response reload share one connection. Audit or reload failure restores the original status and leaves no audit row.
5. **SQLite verification boundary:** real SQLite tests prove equivalent serial outcomes and rollback behavior; a static `select_for_update()` contract preserves the intended MySQL row-lock implementation because SQLite itself cannot demonstrate MySQL row-level locking.
6. State transitions do not read or restore ProductKit stock. Inventory effects remain Phase 4.3 work.

### Verification

- 18 new status-transition test instances were added; the focused status-Service and architecture command passes with 20 tests including existing architecture guards.
- All 262 Order-related contracts pass together.
- The complete suite passes with 1043 tests after the status-Service and documentation updates.

### Release Notes

- No new dependency, database schema change, migration, endpoint, or application-version change is required.
- The existing offline Order migration remains unapplied; no development database was rebuilt.
- Order HTTP APIs remain unavailable until Mapper, dependency composition, and routes are implemented.

---

## Unreleased — Order Creation Service (Phase 4.2.7)

**Date:** 2026-08-13

### Summary

Implemented the Experience-only Order creation orchestration layer. The Service now validates Product/Option aggregates in batches, creates database-authoritative Decimal snapshots, and atomically persists the Order aggregate plus its non-sensitive audit record. Status transitions, mapping, dependency wiring, and HTTP routes remain outside this slice.

### Added

- `OrderItemInput` as a Service-domain input containing only Product ID, ExperienceOption ID, and quantity; no client-controlled snapshot fields enter the use case.
- Batch Product/Option resolution with stable request-order errors, Kit-before-Option behavior, and unified unavailable semantics for missing, deleted, offline, or mismatched aggregates.
- Database-authoritative Product name, Option configuration, price, subtotal, and total snapshots using `Decimal` arithmetic.
- One transaction for Order creation, one-shot Item bulk insertion, sequential `CREATE_ORDER` audit, and complete aggregate reload on the same connection.
- `OrderRepository.order_number_exists()` for post-rollback collision attribution and whole-transaction retry with a fresh order number, capped at three attempts.
- Unit and real SQLite tests for validation priority, batch access, snapshot immutability, audit privacy, complete rollback, collision success, retry exhaustion, and non-collision `IntegrityError` preservation.

### Important Decisions

1. **Database source of truth:** clients cannot submit names, configuration, prices, subtotals, totals, status, user ID, or order number. Every persisted and returned snapshot is reconstructed from the current valid Product/Option rows.
2. **Stable error priority:** bulk loading reduces query count without changing observable validation order. Items are checked in request order; each Item checks the known Kit boundary before Product availability and Option validity/ownership.
3. **Atomic aggregate:** Order, Items, audit, and response reload use one transaction connection. Even an exception after the audit INSERT rolls back every write, and validation failures occur before a transaction or audit begins.
4. **Fresh-transaction retry:** an `IntegrityError` leaves a transaction unusable. Collision attribution therefore occurs only after leaving the transaction context; a confirmed order-number collision opens a new transaction, while unrelated integrity errors retain their original cause.
5. Phase 4.2 creation performs no ProductKit stock read or write. Kit remains an explicit `40922` boundary until the Inventory concurrency model is designed in Phase 4.3.

### Verification

- 16 focused creation-Service unit and real SQLite integration tests pass.
- All 245 Order-related contracts pass together.
- The complete suite passes with 1025 tests after the creation-Service and documentation updates.

### Release Notes

- No new dependency, database schema change, migration, endpoint, or application-version change is required by this slice.
- The existing offline Order migration remains unapplied; no development database was rebuilt.
- Order HTTP APIs remain unavailable until Mapper, dependency composition, and routes are implemented. State-transition Services also remain unimplemented.

---

## Unreleased — Order Query Service (Phase 4.2.6)

**Date:** 2026-08-13

### Summary

Implemented the read-only Order business orchestration layer: user/admin lists, user/admin details, and administrator Order audit-history queries. This slice adds visibility and error semantics without introducing creation, status transitions, response mapping, dependency wiring, or routes.

### Added

- `OrderService.list_user_orders()` / `get_user_order_detail()` with SQL-scoped user visibility and uniform `OrderNotFound` behavior for missing and foreign resources.
- `OrderService.list_admin_orders()` / `get_admin_order_detail()` forwarding the frozen paging, exact order-number, user, status, and UTC time-range contract.
- `OrderService.list_order_audit_logs()` with a lightweight Order existence check before delegation to the shared `AuditLogService` and `target_type="order"` pagination.
- `OrderRepository.get_order_by_id()` as a relation-free existence lookup with optional caller connection.
- A common `OrderStatusValue` API type plus complete `ORDER_STATUS_BY_VALUE` reverse registry for explicit API-string-to-database-Enum translation.
- Mock orchestration, architecture, real SQLite visibility, aggregation, relation-preloading, audit isolation, orphan-audit, and named-exception tests.

### Important Decisions

1. **Resource-enumeration protection:** user detail always queries by `(order_id, user_id)`. Both a missing ID and another user's ID produce Repository `None` and the same `40411 OrderNotFound`; Service never loads a foreign Order and exposes a different ownership error.
2. **Boundary translation:** Query Schema and Service accept stable API values (`pending`, `paid`, `cancelled`, `completed`), while Repository accepts `OrderStatus`. The explicit reverse registry is the only translation boundary, preventing HTTP strings from leaking into persistence code and IntEnum integers from leaking into the API.
3. **Existence before history:** an Order audit query first proves the Order row exists. A stale or orphan `audit_logs` row cannot make a nonexistent Order appear queryable.
4. Query Service performs no direct ORM operation, opens no transaction for pure reads, does not call ProductService, and delegates audit access only through the documented shared-service exception.

### Verification

- 59 focused Enum/Query Schema/Service/Repository tests pass after boundary translation.
- All 212 `test_order_*.py` contracts pass together.
- The complete suite passes with 1009 tests after the query-Service and documentation updates.

### Release Notes

- No database schema, migration, dependency, endpoint, or application-version change is required.
- The Order API remains unavailable until Mapper and routes are implemented.
- Order creation transaction, order-number collision retry, state-transition/audit transactions, Mapper, and routes remain unimplemented.

---

## Unreleased — Order Repository and Number Generator (Phase 4.2.5)

**Date:** 2026-08-13

### Summary

Implemented the Order data-access boundary and dependency-free order-number generator. This slice provides the transaction-aware primitives required by the later query, creation, and state-transition Services without introducing business exceptions, service orchestration, mapping, or HTTP routes.

### Added

- Standard-library `OD` + 26-character Crockford Base32 ULID generation using UTC Unix milliseconds and `secrets.token_bytes()`; no Redis, database sequence, third-party ULID package, or mutable generator state.
- `OrderRepository` creation, one-shot OrderItem `bulk_create()`, ID/number detail loading, optional SQL-level user visibility, transaction-bound `SELECT ... FOR UPDATE`, status persistence, and user/admin pagination.
- Database `COUNT(items)` list summaries, stable `created_at DESC, id DESC` pagination, exact admin order-number/user/status filters, inclusive `created_from`, exclusive `created_to`, and admin User preloading.
- Product/ExperienceOption set loaders in `ProductRepository`; each executes one query, includes logically deleted rows for Service-level availability decisions, and accepts the caller's transaction connection.
- Architecture, source-selection, real SQLite transaction, rollback, query-count, visibility, filtering, paging, snapshot, and order-number tests.

### Important Decisions

1. Repository methods do not raise Order business exceptions or decide ownership, availability, Kit policy, snapshot arithmetic, retry policy, or state transitions. User visibility is expressed as an optional SQL predicate so the query Service can hide missing and foreign resources uniformly.
2. List queries aggregate Item row count and do not preload Item collections. Detail queries preload stable Item order and the User relation in constant query count; the later Mapper must perform zero SQL.
3. `update_status()` persists only a status already approved by Service. Every state-transition Service must lock and recheck the row in the same transaction before calling it.
4. The generator provides approximate time ordering only. `created_at DESC, id DESC` remains authoritative; the database unique constraint and later Service transaction retry remain the collision boundary.

### Verification

- 28 focused generator, Repository, Product batch-loader, architecture, transaction, and performance tests pass, including uncommitted aggregate reload on the caller's transaction connection.
- All 195 `test_order_*.py` domain, Schema, Model, migration, generator, and Repository tests pass together; including the three Product batch-loader contracts, the combined slice has 198 passing tests.
- The complete suite passes with 992 tests after the Repository and documentation updates.

### Release Notes

- No database schema, migration, dependency, endpoint, or application-version change is required.
- The existing Order MySQL migration remains offline and unapplied. No development database was rebuilt or modified outside disposable test schemas.
- Order query Service, creation transaction, status/audit Service, Mapper, and routes remain unimplemented.

---

## Unreleased — Order Models and MySQL Migration (Phase 4.2.4)

**Date:** 2026-08-13

### Summary

Implemented the Order persistence contract: registered `Order` / `OrderItem` Tortoise Models, verified their real SQLite schema and behavior, and generated a reviewed MySQL 8+ incremental migration without connecting to or changing any database.

### Added

- `Order` with unique `OD` + ULID order number, User `RESTRICT` relation, exact Decimal total, `SmallIntField` status with ORM/database default `0`, nullable remark, and four named stable-pagination indexes.
- `OrderItem` with Order/Product/ExperienceOption `RESTRICT` relations, nullable future-Kit Option fields, immutable product/configuration/price snapshots, strict quantities and amounts, and the named `(order_id, id)` index.
- Real temporary-SQLite contracts for Model metadata, default values, Decimal/Enum round trips, reverse relations, field boundaries, unique order numbers, physical-delete protection, exact index columns, nullable extension fields, and DDL foreign keys.
- Offline MySQL migration `1_20260813130455_add_order_tables.py` plus static contracts for its exact table scope, field types, defaults, four foreign keys, five indexes, non-transactional MySQL DDL semantics, safe child-before-parent downgrade order, and Aerich model state.

### Important Decisions

1. Order status uses the project's actual Tortoise/MySQL integer-enum mapping, `SmallIntField` / `SMALLINT`, rather than the stale `TINYINT` wording in the frozen draft. Database design and DBML were corrected together.
2. Cross-field Option completeness, duplicate Item combinations, Product availability, snapshot arithmetic, Kit rejection, and state transitions remain Schema/Service responsibilities; Models contain no business workflow or database queries.
3. Nullable Option fields remain in the physical table for Phase 4.3 Kit compatibility, while Phase 4.2 Service must reject every Kit Item.
4. Aerich's generated MySQL migration was reviewed to remove `IF NOT EXISTS`, declare `RUN_IN_TRANSACTION = False`, and drop `order_items` before `orders` on an explicitly authorized downgrade.

### Verification

- 22 focused Order Model tests pass.
- 29 combined Order Model, Order migration, and initial MySQL migration tests pass.
- The complete suite passes with 964 tests after the persistence and documentation updates.

### Release Notes

- The incremental migration was generated with `AERICH_MYSQL_VERSION=8.0` and `aerich --app models migrate --offline`; no `upgrade`, `downgrade`, `--fake`, development-database rebuild, or live database connection was performed.
- Applying the migration later requires a separately authorized target, schema audit, backup, and execution plan. Its downgrade deletes all Order data and must never be treated as routine rollback.
- No dependency, endpoint, or application-version change is required. Order Repository, Service, Mapper, routes, and order-number generator remain unimplemented.

---

## Unreleased — Order Schema Contracts (Phase 4.2.3)

**Date:** 2026-08-13

### Summary

Implemented strict Order creation, list-query, and user/admin response Schema contracts without introducing database Models, business Services, Mappers, or routes.

### Added

- `OrderItemCreate` and `OrderCreate` with strict IDs/quantity, 1–10 Items, duplicate Product/Option rejection, remark normalization, unknown-field rejection, and server-owned field isolation.
- `OrderListQuery` and `AdminOrderListQuery` with API-string status values, exact order-number filtering, safe query-ID parsing, UTC-aware date ranges, and strict range ordering.
- `OrderItemOut`, user/admin list and detail outputs, and lightweight status output with explicit field whitelists.
- Decimal-only response amounts serialized as fixed two-place strings, Product-price upper bounds, status/day-type value-label consistency, Item subtotal validation, and Order total validation.
- User/admin isolation contracts: user responses omit all user data; admin responses add only `user_id` and `user_nickname`; detail responses do not repeat the list-derived `item_count`.

### Important Decisions

1. Query status accepts only API values (`pending`, `paid`, `cancelled`, `completed`) and never database IntEnum integers.
2. Query datetimes and response datetimes must be explicitly UTC; naive and non-UTC-offset values are rejected.
3. Out Schema accepts internal monetary values only as `Decimal`; strings and floats are rejected before fixed two-place serialization.
4. The response layer validates snapshot arithmetic but does not query or mutate any ORM object.

### Verification

- 116 focused Order Schema tests pass; all 144 Order domain and Schema tests pass together.
- The complete suite passes with 938 tests after all implementation and documentation updates.

### Release Notes

- No database migration, dependency, endpoint, or application-version change is required.
- Order Model, Repository, Service, Mapper, routes, and migration remain unimplemented.

---

## Unreleased — Order Domain Contracts (Phase 4.2.2)

**Date:** 2026-08-13

### Summary

Implemented the first Order code slice after the v1.0 contract freeze: database status Enum, fixed business boundaries, API display registries, audit constants, and HTTP-semantic named exceptions. No database, Schema, Service, or route behavior is introduced by this slice.

### Added

- `OrderStatus(IntEnum)` with stable database values 0–3.
- Explicit OrderStatus API value and Chinese label registries, preventing IntEnum database integers from leaking into API status output.
- Frozen constants for Item count, quantity, remark length, ULID order-number shape and retry limit, Phase 4.3 Kit boundary, and four audit actions.
- `OrderNotFound`, `OrderStatusConflict`, `KitOrderingRequiresInventory`, `OrderProductUnavailable`, and `OrderOptionUnavailable`, exported through the common exception package.
- Enum/constant and exception contracts covering inheritance, payloads, invalid construction, JSON behavior, and global HTTP 404/409/422 mappings.

### Important Decisions

1. OrderStatus remains an `IntEnum` for the database; API values are obtained only through an explicit registry.
2. Named exceptions validate their structured payload at construction so invalid IDs or status types cannot produce unstable public error data.
3. Request-shape errors remain the responsibility of the next Schema stage and are not duplicated as business exceptions.

### Verification

- 27 focused Order domain contract tests pass.
- The complete suite passes with 821 tests after all implementation and documentation updates.

### Release Notes

- No database migration, dependency, endpoint, or application-version change is required.
- Order Schema, Model, Repository, Service, Mapper, routes, and migration remain unimplemented.

---

## v0.4.0 — Product Module Implementation (Unreleased)

**Date:** 2026-08-13

### Summary

Completed the Product module implementation and its final architecture, OpenAPI, documentation, and release-readiness review. The Product API contract is now v1.0 Implemented. This section is the v0.4.0 release-candidate summary; the following Unreleased Phase 4.1 sections retain the detailed implementation history.

### Changed

- Added precise generic OpenAPI success and error envelopes for all 22 Product operations while preserving the Mapper as the single runtime serialization boundary.
- Verified that all 19 admin Product operations require Bearer authentication, all 3 public Product operations remain anonymous, and every application operation ID is unique.
- Removed the obsolete Phase 3 demo `GET /api/v1/admin/users` registration; the formal admin-users router remains the only owner of that path.
- Synchronized Product business rules, API conventions, architecture, AI context, and project instructions with the implemented Phase 4.1 state.

### Important Decisions

1. Product routes declare precise OpenAPI models through `responses` with `response_model=None`; this avoids revalidating Mapper-produced decimal strings while retaining strict one-pass Out Schema validation.
2. The Product API document advances from Draft v0.9 to Implemented v1.0. This is a contract-document version, not an application release or Git tag.
3. The code/default configuration advances from v0.3.0 to the unreleased v0.4.0 candidate because this release adds the complete Product feature set rather than a backward-compatible bug fix. No Git tag or release is created by this change.

### Verification

- 51 focused Product API route, OpenAPI, and real SQLite HTTP tests pass.
- The complete suite passes with 794 tests, including two application-version consistency contracts.
- Python compilation, dependency integrity, OpenAPI warning/operation/security checks, whitespace, debug-output, and unfinished-marker checks pass.

### Release Notes

- No new database migration is introduced by this review. The existing MySQL 8+ initial migration remains unapplied and still requires an explicitly authorized deployment procedure.
- No cleanup command was run against the development database or upload directory.

---

## Unreleased — Product Image Delayed Cleanup (Phase 4.1)

**Date:** 2026-08-13

### Summary

Implemented a retryable operational batch that removes local files only after ProductImage logical deletion is durably committed, without coupling irreversible file I/O to the DELETE request transaction.

### Added

- Repository ID-cursor scan for deleted images at or before an explicit cutoff.
- `ProductImageCleanupService` with managed-URL validation, active-reference protection, idempotent deletion, per-item failure isolation, and batch statistics.
- `python -m app.tasks.product_image_cleanup --before <timezone-aware ISO 8601>` operational command with bounded batches and failure exit status.
- Real SQLite and temporary-filesystem tests for cutoff selection, cursor pagination, managed/external URLs, active URL references, missing objects, failures, and unsafe parameters.

### Important Decisions

1. Cleanup does not run inside ProductService, FastAPI BackgroundTasks, application startup, or the logical-delete transaction.
2. Existing `is_deleted`, `updated_at`, and `image_url` fields are the durable retry source; ProductImage and AuditLog records remain intact, so no cleanup-status table or migration is needed.
3. The cutoff is mandatory and timezone-aware. Retention policy remains an explicit deployment choice rather than an application magic number; the command defaults to preview and requires `--apply` for deletion.
4. A failed object remains discoverable on the next run. A missing object is treated as idempotent success, while unmanaged/external URLs are never passed to local storage deletion.

### Verification

- 39 focused storage, Repository, cleanup Service, task orchestration, architecture, real SQLite, filesystem, batch-query, and preview-safety tests pass.

### Operational Note

- The command is implemented but was not executed against the workspace development database or upload directory. Production scheduling remains a deployment responsibility.
- No database migration, dependency, API endpoint, or application version change is required.

---

## Unreleased — Product Audit History API (Phase 4.1)

**Date:** 2026-08-13

### Summary

Implemented the shared AuditLog read path and exposed Product operation history as an ADMIN+ paginated endpoint without embedding audit data in Product detail or duplicating its Schema in the Product module.

### Added

- Shared `AuditLogRepository.list_logs()` and `AuditLogService.list_logs()` target-scoped pagination.
- Shared `AuditLogOut`, strict pagination query Schema, and Audit API Mapper field whitelist.
- `GET /api/v1/admin/products/{product_id}/audit-logs`, including logically deleted Product records.
- Repository, Service, Mapper, permission, validation, route-contract, and real SQLite HTTP tests.

### Important Decisions

1. ProductService checks Product existence with `include_deleted=true`, then delegates the actual query to the shared AuditLogService.
2. Logs are ordered by `created_at DESC, id DESC` so pagination remains deterministic when timestamps collide.
3. The public audit shape omits `updated_at`; audit entries are immutable event records for this read contract.
4. Audit logs remain an independent paginated resource and are not loaded into Product list or detail queries.

### Verification

- 54 focused Audit/Product route, Service, Mapper, architecture, permission, validation, and real SQLite tests pass.

### Known Limitations

- ProductImage delayed physical cleanup was completed by the later stage above.
- No database migration, dependency, or application version change is required.

---

## Unreleased — Product Multipart Image Routes (Phase 4.1)

**Date:** 2026-08-13

### Summary

Connected Product and ExperienceOption image uploads to ADMIN+ multipart FastAPI routes, the completed local storage adapter, ProductService, API mappers, and development static-file serving.

### Added

- HTTP 201 `POST /api/v1/admin/products/{product_id}/images` and `POST /api/v1/admin/options/{option_id}/images`.
- Strict multipart Pydantic forms: public images accept only file/is_cover/sort; Option images accept only file/sort and reject `is_cover`.
- API upload orchestration that runs synchronous storage off the event loop, closes spooled upload files, and compensates a stored file when ProductService fails without masking the original exception.
- Deferred-directory local static serving for generated `/uploads/products/{uuid}.{ext}` URLs.
- Real SQLite multipart tests covering file persistence, Product/Option ownership, audit ordering, safe filenames, response mapping, and static retrieval.

### Important Decisions

1. ProductService remains unaware of UploadFile and storage. The API boundary passes only the generated image URL.
2. Multipart validation errors use the existing unified request-validation envelope; invalid content/MIME/size uses named `42221 InvalidImageFile`.
3. Compensation failures are logged with the opaque storage key and do not replace the original Service exception.
4. Local static serving is a development adapter. A non-path external base URL is not mounted and can be supplied by a future object-storage deployment adapter.

### Verification

- 57 focused multipart route, real SQLite, storage, security, and architecture tests pass.

### Known Limitations

- ProductImage delayed physical cleanup was completed by the later stage above.
- Product audit-history listing was completed by the later stage above.
- No database migration or application version change is required. Runtime dependency `python-multipart==0.0.32` was added.

---

## Unreleased — Product Image Storage Adapter (Phase 4.1)

**Date:** 2026-08-13

### Summary

Implemented the Product image validation and local-storage boundary without coupling ProductService to FastAPI or file I/O. Multipart routes remain a separate next step.

### Added

- `LocalImageStorage` with a 2 MiB bounded read, jpg/png/webp signature detection, declared-MIME consistency checks, server-generated UUID keys, non-overwriting atomic publication, URL generation, and idempotent compensation deletion.
- Named `42221 InvalidImageFile` with a stable `data.reason` contract.
- Environment-configurable local upload directory/base URL, plus repository ignore rules for runtime uploads.
- Unit, security, architecture, and global exception-mapping tests.

### Important Decisions

1. Client filenames never enter the storage key or filesystem path; only adapter-generated lowercase UUID keys and allowlisted extensions are accepted.
2. Validation happens before the destination directory or final object is created. Temporary files are cleaned on any publication failure, and an existing target is never overwritten.
3. The adapter returns both a public URL for ProductService and an opaque key for route-level compensation. It does not import FastAPI, Models, Repositories, or Services.
4. Multipart parsing, calling ProductService, compensating a stored file when Service fails, static-file serving, and delayed cleanup after logical deletion remain in the next API integration step.

### Verification

- 23 focused storage, security, architecture, exception-contract, and HTTP exception-mapping tests pass.

### Known Limitations

- Resolved by the later Product Multipart Image Routes stage above: both image-create endpoints are now registered and callable.
- No database schema, migration, dependency, or application version change is required.

---

## Unreleased — Product JSON FastAPI Routes (Phase 4.1)

**Date:** 2026-08-13

### Summary

Connected the completed Product Service and API Mapper layers to 19 callable FastAPI endpoints for public/admin queries and ordinary JSON mutations. Multipart image creation and audit-history listing were separate follow-up stages at that point and are now complete above.

### Added

- Public Product list plus Experience/Kit detail routes.
- ADMIN+ Product list/detail, create/update/delete, online/offline, Option lifecycle, Kit price/stock, and ProductImage metadata/delete routes.
- `get_product_service()` API composition dependency for ProductRepository + shared AuditLogService + ProductService.
- Global `RequestValidationError` conversion to the project response envelope without echoing original input values.
- Route contract, architecture, permission, validation, status-code, response isolation, and real SQLite HTTP lifecycle tests.

### Important Decisions

1. Routes depend on ProductService, never Product Model/Repository; they only validate transport input, invoke Service, map the result, and call `success()`.
2. Product creates return HTTP 201. ExperienceOption creates return 201 for a new record and 200 when restoring its historical ID.
3. Query parameter models use FastAPI `Query()` so `extra="forbid"` rejects unknown query parameters at the HTTP boundary.
4. PATCH routes pass `model_dump(exclude_unset=True)` to preserve missing versus explicit null semantics.
5. ProductImage JSON PATCH/DELETE were included in this stage because they required no file content; the later Product Multipart Image Routes stage above registered both image POST routes.
6. Request validation errors expose only location, message, and type. Raw request values are not included in the response or warning log.

### Verification

- 31 focused Product API route, architecture, and real SQLite integration tests pass.
- All 629 Product tests pass.
- Real HTTP flows cover Experience/Kit creation, queries, state transitions, mutations, response IDs, availability, and persisted ordered audits.

### Known Limitations

- Product/Option multipart creation, validation/storage, Service-failure compensation, delayed cleanup, and Product audit-history listing were completed by the later stages above.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — Product API Mapper (Phase 4.1)

**Date:** 2026-08-13

### Summary

Completed the Product API response adaptation boundary. Product Service ORM/Page results can now be converted synchronously and without SQL into strict user/admin Out Schemas. FastAPI routes and image file storage remain separate pending work.

### Added

- `app/api/mappers/product.py` mappings for user/admin pages, Experience/Kit details, Product/Option/Image/Kit mutation responses, image ownership, dimensions, availability, covers, prices, and value labels.
- Authoritative Product type/status/day-type label registries and open duration/participant label rules in Product constants.
- Architecture tests prohibiting async/await, ORM query/mutation calls, and Service/Repository/FastAPI/Redis dependencies.
- Unit and real SQLite tests for response whitelists, user/admin isolation, aggregate completeness, ID semantics, stable dimensions, zero SQL, and zero ORM mutation.

### Important Decisions

1. Mapper functions construct explicit whitelisted dictionaries and immediately validate them with the corresponding Product Out Schema; prices remain `Decimal` until Schema serialization fixes them to two decimal places.
2. User mappers fail fast for non-Online/deleted/incomplete aggregates instead of fabricating empty covers, zero prices, or missing Kit extensions. Admin mappers permit documented Draft emptiness.
3. Mapper consumes Repository-established relation ordering and never reloads or expands the data scope. Unprefetched relationships remain programming errors.
4. Kit price/stock mutation response IDs use `ProductKit.product_id`, never the ProductKit table primary key.
5. Existing Service return values and Repository preloads already satisfy response mapping, so no Service/Repository compatibility changes were needed.

### Verification

- 32 focused Mapper unit and architecture tests pass.
- 3 real SQLite Mapper integration tests pass with SQL execution disabled after Repository loading.
- All 597 Product tests pass.

### Known Limitations

- Ordinary Product JSON FastAPI routes, ADMIN+ dependencies, and `success()` integration are complete. Multipart parsing, image validation/storage, and external-file compensation remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ProductImage Lifecycle Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Completed ProductImage database lifecycle orchestration: public and Option image creation, atomic cover switching, partial metadata updates, and logical deletion. Multipart validation, external storage, and API routing remain separate pending integration work.

### Added

- `ProductImageNotFound` (`40403`) and `OptionImageCannotBeCover` (`40021`) with stable HTTP mappings.
- Product and Option image creation Services with fixed ownership, Option non-cover enforcement, cover clearing, and Product-targeted audits.
- Image sort/cover update and logical-delete Services with hidden deleted parents, ordered one/two-audit flows, and compact snapshots.
- Repository Product-row lock and cover lookup on the caller transaction, with mock/real SQLite tests for cover invariants and rollback.

### Important Decisions

1. Service accepts a storage-generated image URL; FastAPI UploadFile, 2MB/type/content checks, external storage, and `42221` remain API/infrastructure responsibilities.
2. If storage succeeds before a database Service failure, the future caller must delete the object or enqueue delayed cleanup because the database transaction cannot roll back external storage.
3. Cover creation/switching locks the Product row so concurrent cover requests for one aggregate are serialized before bulk cover clearing.
4. Deleted Image/Product/Option ownership is hidden behind `40403`; an Option image cover attempt uses the registered `40021` contract.
5. Delete audit omits the potentially 2048-character URL to fit the existing 256-character AuditLog description. The logical-deleted ProductImage remains the authoritative URL record addressable by image ID.

### Verification

- 71 focused Image Service, Repository, exception, and architecture tests pass.
- All 559 Product tests pass.
- Full regression: 666 tests pass.
- Real SQLite tests prove one effective public cover and rollback of cover creation, second cover audit, and deletion failures.

### Known Limitations

- Multipart routes, image validation, storage adapter, compensation/delayed cleanup, and response mapping were completed by the later stages above.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ProductKit Mutation Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented atomic Kit price changes and direct final-stock settings, completing the ProductKit mutation Service boundary. The HTTP endpoints remain unavailable until API integration.

### Added

- `ProductService.update_kit_price()` and `update_kit_stock()` with shared ordered Product/Kit aggregate checks.
- Named `ProductKitNotFound` using the existing `40404` API allocation when a valid Kit Product lacks its required extension record.
- Compact `UPDATE_PRICE` and `UPDATE_STOCK` before/after snapshots in the existing AuditLog description field.
- Mock and real SQLite tests for error precedence, Draft/Offline writes, zero stock, field preservation, Validator isolation, write failure short-circuiting, and audit-failure rollback.

### Important Decisions

1. Checks run in the stable order missing Product, deleted Product, type mismatch, Online state, and missing ProductKit extension.
2. Price and stock remain separate use cases and each changes exactly one ProductKit field.
3. Phase 4.1 stock mutation sets the final value; stock movements, reasons, automatic deduction/restoration, and concurrency control remain Phase 4.3 Inventory work.
4. ProductKit mutation and its Product-targeted audit share one transaction. Service returns ProductKit; the future API Mapper uses `product_id` as the response ID.

### Verification

- 51 focused Kit mutation, exception, and architecture tests pass.
- All 530 Product tests pass.
- Full regression: 637 tests pass.
- Real SQLite tests prove field preservation and audit-failure rollback for both mutations.

### Known Limitations

- Kit price/stock API routes and response mappings remain pending.
- Product image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ExperienceOption Delete Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Completed the ExperienceOption lifecycle Service by implementing status-safe logical deletion with atomic snapshot auditing. The HTTP endpoint remains unavailable until API integration.

### Added

- `ProductService.delete_experience_option()` with ordered missing/deleted/Product-state checks and Draft/Offline logical deletion.
- Compact `DELETE_OPTION` snapshots containing Option identity, dimensions, day type, and two-decimal price in the existing AuditLog description field.
- Mock and real SQLite tests for conflict precedence, deleting the final active Option, Product status preservation, image record/foreign-key preservation, Validator isolation, write failure short-circuiting, and audit-failure rollback.

### Important Decisions

1. A deleted parent Product hides its Option behind `40402`; an already-deleted Option retains `40912` precedence over Product Online status.
2. Deletion changes only `ExperienceOption.is_deleted`. Product status and ProductImage records are not modified, and no physical delete occurs.
3. Draft/Offline may reach zero active Options. The delete workflow does not count siblings or invoke ProductValidator; a later online request owns aggregate completeness enforcement.
4. Option mutation and `DELETE_OPTION` audit share one transaction and target the Product for unified product-history lookup.

### Verification

- 39 focused Option delete, exception, and architecture tests pass.
- All 506 Product tests pass.
- Full regression: 613 tests pass.
- Real SQLite tests prove final-Option deletion, unchanged Product/image state, and audit-failure rollback.

### Known Limitations

- The ExperienceOption delete API route and response mapping remain pending.
- Kit mutation and image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ExperienceOption Update Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented partial ExperienceOption mutation with merged all-history uniqueness checks and atomic configuration/price auditing. The HTTP endpoint remains unavailable until API integration.

### Added

- `ExperienceOptionNotFound` (`40402`) and `ExperienceOptionAlreadyDeleted` (`40912`) with fixed HTTP contracts.
- `ProductService.update_experience_option()` with non-empty field allowlisting, API-to-Model duration mapping, Product state protection, merged final-combination validation, and race-time unique conflict translation.
- Separate `UPDATE_OPTION` dimension snapshots and `UPDATE_PRICE` price snapshots; one PATCH can atomically write both actions in deterministic order.
- Mock and real SQLite tests for omitted-field preservation, current-ID exclusion, active/deleted history collisions, deleted Product hiding, Online protection, image preservation, Validator isolation, and rollback on first/second audit or response reload failure.

### Important Decisions

1. Service receives `model_dump(exclude_unset=True)` output rather than a Pydantic Schema and rejects empty or internal-field mappings before any lookup.
2. Uniqueness is evaluated against the merged final dimensions. The current Option row is allowed; any other historical row is a `40911`, including deleted rows.
3. Configuration and price use their authoritative separate audit actions. Both audit rows target the Product so the existing product-history endpoint can return them.
4. Update, all audits, and response aggregate reload use the same transaction connection. Option images are neither modified nor included by the future `ExperienceOptionBaseOut` response.

### Verification

- 58 focused Option update, exception, Repository, and architecture tests pass.
- 512 Product/Option/audit tests and the complete 600-test suite pass.
- Real SQLite tests prove field persistence, image preservation, deterministic dual audits, and complete rollback when either audit or response reload fails.

### Known Limitations

- The ExperienceOption update API route and response mapping remain pending.
- Option delete, Kit mutation, and image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ExperienceOption Create and Restore Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented atomic ExperienceOption creation and historical-record restoration while preserving the all-history combination identity contract. The HTTP endpoint remains unavailable until API integration.

### Added

- `ProductTypeMismatch` (`40001`) and `ExperienceOptionAlreadyExists` (`40911`) with frozen response data.
- `ProductService.create_experience_option()` with Product preconditions, all-history combination lookup, INSERT/restore branching, and shared transaction audit persistence.
- `ExperienceOptionCreationResult(option, restored)` so the API can select HTTP 201 for creation and HTTP 200 for restoration without introducing transport concerns into Service.
- Repository Option detail loading with parent Product and sorted active images, including caller-owned transaction support.
- Mock and real SQLite tests for Draft/Offline creation, Product conflicts, active duplicates, concurrent unique-index translation, original ID/image preservation, price snapshot auditing, Validator isolation, and audit-failure rollback.

### Important Decisions

1. A deleted matching combination is restored in place with its original Option ID and image foreign keys; only current price and `is_deleted` change.
2. The Service lookup gives an early `40911`, while the database all-history unique index remains the concurrency authority. A race-time `IntegrityError` is translated to the same business conflict.
3. Creation/restoration, audit, and response aggregate reload use one transaction connection. `CREATE_OPTION` and `RESTORE_OPTION` target the Product so the existing product-history endpoint can return them.
4. AuditLog has no metadata column; restoration stores compact JSON with Option ID and before/after price strings in the existing `description` field. No migration is introduced.

### Verification

- 47 focused Option create/restore, exception, Repository, and architecture tests pass.
- 484 Product/Option/audit tests and the complete 572-test suite pass.
- Real SQLite tests prove new-record persistence, restoration identity/image preservation, and rollback of both paths when audit fails.

### Known Limitations

- The ExperienceOption create/restore API route and response mapping remain pending.
- Option update/delete, Kit mutation, and image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — Product Update and Delete Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented Product basic-information PATCH orchestration and Product logical deletion with stable conflicts and atomic audit persistence. The HTTP endpoints remain unavailable until API integration.

### Added

- `OnlineProductCannotBeModified` (`40905`) and `ProductMustBeOfflineBeforeDelete` (`40904`) with fixed messages and HTTP 409 mapping.
- `ProductService.update_product()` with non-empty `name` / `description` field allowlisting, PATCH missing/null preservation, ordered preconditions, and atomic `UPDATE_PRODUCT` audit persistence.
- `ProductService.delete_product()` with Draft/Offline support, status-preserving logical deletion, and atomic `DELETE_PRODUCT` audit persistence.
- Mock and real SQLite tests for missing/deleted/Online conflicts, deletion precedence, forbidden internal fields, Validator isolation, child-record preservation, shared transaction connections, failure short-circuiting, and audit-failure rollback.

### Important Decisions

1. API passes `ProductUpdate.model_dump(exclude_unset=True)` as a normalized field mapping; Service remains independent of Pydantic while preserving omitted fields versus explicit `description=None`.
2. Service allowlists only `name` and `description`, so type, status, and deletion state remain owned by their dedicated use cases.
3. Logical deletion changes only `Product.is_deleted`; status and Product child records remain untouched for traceability.
4. Neither workflow loads the aggregate or invokes ProductValidator because no online-readiness transition occurs.

### Verification

- 39 focused update/delete, exception, and architecture tests pass.
- 447 Product/audit transaction tests and the complete 549-test suite pass.
- Real SQLite tests prove successful field/deletion persistence and audit-failure rollback.

### Known Limitations

- Product update/delete API routes and response mapping remain pending.
- Option, Kit mutation, and image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — Product Creation Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented atomic Experience and Kit Draft creation workflows with mandatory Product audit logging. Product HTTP creation endpoints remain unavailable until API integration.

### Added

- `create_experience_product()` with fixed Experience type and atomic Product plus `CREATE_PRODUCT` audit persistence.
- `create_kit_product()` with fixed Kit type and atomic Product, ProductKit, and audit persistence.
- Mock orchestration tests and real SQLite tests for shared transaction connections, fixed types/defaults, zero-stock Kit creation, failure short-circuiting, and full rollback on audit failure.

### Important Decisions

1. Service accepts normalized domain fields rather than Pydantic request objects and returns the created Product Model.
2. ProductType is selected by the Service method; Draft and non-deleted defaults remain Model-owned and cannot be overridden by callers.
3. Draft creation does not invoke ProductValidator and permits incomplete descriptions, images, and Experience Options.

### Verification

- 44 focused Product creation/query/status/architecture tests pass.
- The complete suite passes with 524 tests.

### Known Limitations

- Product creation API routes and response mapping remain pending.
- Product update/delete, Option, Kit mutation, and image Service workflows remain pending.

---

## Unreleased — Product Query Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented the Product query orchestration boundary for admin and public consumers while deliberately leaving presentation mapping to the future API layer.

### Added

- Admin Product list orchestration with pagination, type/status/keyword filters, and explicit logical-deletion scope.
- Public Product list orchestration that forces Online and non-deleted visibility and searches both name and description.
- Admin typed-detail lookup that includes deleted aggregates while hiding type mismatches as `40401`.
- Public typed-detail lookup that hides missing, deleted, non-Online, and type-mismatched resources behind the same `40401` contract.
- Mock contract tests and real SQLite tests for visibility, description search, type isolation, pagination delegation, and relation preloading.

### Important Decisions

1. Query Service returns `Product` or `Page[Product]`; it does not depend on API response Schemas.
2. `cover_image`, `display_price`, dimensions, availability, and value labels belong to an API Mapper built from preloaded aggregates.
3. Query operations do not open transactions, write audit logs, or invoke ProductValidator.

### Verification

- 35 focused Product query/status/architecture tests pass.
- The complete suite passes with 515 tests.

### Known Limitations

- Product API routes and presentation mapping are still unavailable.
- Product creation, update/delete, Option, Kit mutation, and image Service workflows remain pending.

---

## Unreleased — Product Offline Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Completed the Product status-transition Service pair by implementing atomic Online-to-Offline orchestration. The Product HTTP endpoint remains unavailable until the API layer is implemented.

### Added

- `ProductAlreadyOffline` (`40902`) as the stable conflict for both Draft and Offline Products receiving an offline request.
- `ProductService.offline_product(product_id, *, operator_id, ip_address) -> Product` using a lightweight Product lookup, ordered precondition checks, and atomic status plus `OFFLINE_PRODUCT` audit persistence.
- Tests for missing/deleted/non-Online Products, deletion precedence, absence of Validator calls, exact load/update/audit order, shared transaction connections, update failure, successful real persistence, and audit-failure rollback.

### Important Decisions

1. Draft and Offline share `40902` because both are already non-selling states; no additional Draft-specific code is introduced.
2. Offline uses `get_product_by_id(..., include_deleted=True)` because it needs no aggregate relations and never calls the online-readiness Validator.
3. Resource and status conflicts occur before the transaction; the status update and audit remain atomic within one caller-owned transaction.

### Verification

- 34 focused Product status-transition, exception, and architecture tests pass.
- The complete suite passes with 503 tests.
- Real SQLite tests prove successful persistence and audit-failure rollback to Online.

### Known Limitations

- No Product API routes are registered yet.
- Remaining Product query, creation, update/delete, Option, Kit, and image Service operations remain pending.

---

## Unreleased — Product Online Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented the first Product Service slice: precondition checks, Validator orchestration, and atomic online-status plus audit persistence. Product API routes remain unavailable; this milestone exposes no new HTTP endpoint.

### Added

- General `ConflictException` and HTTP 409 middleware mapping without error-code-range inference.
- Named `ProductNotFound`, `ProductIsDeleted`, and `ProductAlreadyOnline` exceptions with frozen 404/409 contracts.
- Caller-owned transaction support in `AuditLogRepository.create()` and `AuditLogService.log()` through optional `using_db` propagation.
- `ProductService.online_product(product_id, *, operator_id, ip_address) -> Product` with complete aggregate loading, ordered resource/state checks, synchronous Validator invocation, atomic status update, and `ONLINE_PRODUCT` audit.
- Service tests for exact orchestration order, Draft and Offline transitions, Experience and Kit aggregates, failure short-circuiting, shared transaction connections, update failure, audit failure rollback, and architecture boundaries.

### Important Decisions

1. Product named exceptions directly inherit the matching HTTP-semantic base; the former 422-only `ProductException` pseudo-base was removed.
2. Service returns the updated ORM Product. API remains responsible for ADMIN+ authorization and `ProductOnlineOut` serialization.
3. Validation and resource/state conflicts occur before the write transaction. Status persistence and audit persistence share one transaction connection and roll back together.
4. This slice does not add row locking, conditional status updates, or cross-request idempotency; concurrent online requests remain a documented future concurrency concern.

### Verification

- 72 Product online/exception/Validator/audit/architecture tests pass.
- The complete suite passes with 493 tests.
- Real SQLite tests prove both successful Experience/Kit persistence and audit-failure status rollback.

### Known Limitations

- No Product API route is registered yet, so the documented online endpoint remains unavailable.
- Remaining Product Service operations—query, create/update/delete, offline, Options, Kit edits, and images—remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — Product Validator (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented and reviewed the Product pre-online aggregate-integrity Validator as a synchronous, pure business component. It reports all readiness issues in stable order through the frozen HTTP 422 / `42201` contract. Product Service and API routes remain unavailable and are intentionally outside this milestone.

### Added

- `UnprocessableEntityException` as the general HTTP 422 business-exception type while preserving HTTP 400 for ordinary `BusinessException` instances.
- `ProductException` and `ProductNotReadyForOnline`, fixing code `42201`, message `Product is not ready to go online`, and non-empty `data.issues` structure.
- `ProductValidator.validate_before_online(product) -> None` as a synchronous entry point that reads a Service-preloaded Product aggregate and either returns `None` or raises the named exception.
- Common online-readiness rules for non-blank Product name and description plus an active public cover.
- Experience rules for at least one public image, at least one active Option, positive Option prices, and at least one active image per Option.
- Kit rules for a required ProductKit extension, price in `(0, 99999]`, and non-negative stock, including support for online products with zero stock.
- Contract tests for exception mapping, every common and type-specific boundary, multi-issue aggregation, stable issue ordering, fail-closed ProductType dispatch, real Repository-loaded aggregates, zero validation-time SQL, no aggregate mutation, and unprefetched-relation programming errors.

### Important Decisions

1. **Validator is a separate component serving Service.** Service owns lookup, resource/state conflicts, transactions, persistence, and audit; Validator owns only aggregate-integrity decisions.
2. **Purity is expressed by a synchronous API.** Validator performs no database, Repository, Service, Redis, transaction, permission, audit, or state-mutation work.
3. **Input must be a complete aggregate.** Service must call `ProductRepository.get_product_detail(product_id, include_deleted=True)` before validation. Missing prefetches remain visible programming errors instead of becoming `42201`.
4. **All issues are returned together.** Stable English strings and ordering are part of the API contract; the Product business rules document is their authoritative list.
5. **Type dispatch fails closed.** Unknown Product types raise an internal programming error rather than passing only common checks or being mislabeled as incomplete business data.
6. **Option identity is not revalidated online.** The Option write flow and the all-history database unique index own configuration conflicts and their `40911` response.

### Verification

- Validator stage tests pass: 6 exception-contract, 11 common-rule, 10 Experience, 11 Kit, and 5 purity/integration tests.
- Product-related tests pass with 366 tests; the complete suite passes with 464 tests.
- Python compilation, dependency integrity, whitespace, forbidden dependency, debug-output, and unfinished-marker checks pass.

### Known Limitations

- Product Service, API routes, permissions, state-transition persistence, transactions, and Product audit-log writes remain pending.
- Product API documentation remains Draft until endpoint integration tests pass.
- Image file upload and MIME/size validation remain pending; `42221` is reserved for that later boundary.
- The committed MySQL initial migration remains unapplied. This Validator milestone changes no schema and requires no migration.

---

## Unreleased — Product Repository (Phase 4.1)

**Date:** 2026-08-11

### Summary

Implemented and reviewed the Product aggregate Repository as the data-access boundary for the upcoming Validator and Service slices. Product endpoints remain unavailable until Validator, Service, and API integration are complete.

### Added

- `ProductRepository` with Product create/update, logical-delete-aware lookup, filtered pagination, and aggregate detail loading.
- ExperienceOption lookup by ID and all-history configuration identity, plus transaction-aware create/update operations that support restoration orchestration without creating a second version row.
- ProductKit and ProductImage lookup/create/update operations, including one-statement public-cover clearing scoped by Product, logical deletion, and optional current-image exclusion.
- Use-case-specific relation loading: list summaries preload Kit, active Options, and active public images; details additionally preload active Option images; Option/Image ID lookups preload the parent records required by Service rules.
- Repository contract tests for normal paths, deletion scope, stable ordering, pagination metadata, transaction rollback, parent relations, and constant-query-count protection against N+1 behavior.

### Changed

- `Page[T]` now permits ORM Model item types so Repository code can return `Page[Product]` while API code continues using response-Schema pages.
- Consolidated the identical partial-update persistence mechanism behind a private bounded generic helper while retaining entity-specific public methods and return types.
- Rebuilt the active SQLite development database from current Tortoise Models after creating a recoverable backup. No MySQL migration was applied to SQLite and no Aerich version was faked.

### Important Decisions

1. **Repository returns Models, not API DTOs.** Service owns derived fields such as `cover_image` and `display_price`; API owns Out-Schema serialization.
2. **Transactions are Service-owned.** Repository writes accept an optional database client and join the caller's transaction without deciding transaction boundaries.
3. **Loading follows the use case.** Lists do not fetch Option images, details do, and child-resource lookups join only the parent records needed by Service checks.
4. **Logical deletion is explicit per query.** Ordinary lookups hide deleted rows, while the all-history Option identity query intentionally includes deleted records so Service can restore the stable Option ID.
5. **Cover switching is batch persistence, not a Repository business rule.** Repository provides one scoped UPDATE; Service must decide whether a cover change is valid and execute the full switch atomically.
6. **Reuse stays local until generalized behavior is proven.** Common update mechanics are private to the Product Repository module rather than imposed through a premature global BaseRepository.

### Verification

- 38 Product Repository tests pass, including bounded query-count and transaction rollback contracts.
- The complete test suite passes with 421 tests.
- Python compilation, dependency integrity, whitespace, forbidden dependency, and debug-output checks pass.

### Known Limitations

- Product Validator, Service, API routes, upload handling, and business exceptions remain pending.
- Product API documentation remains Draft until endpoint integration tests pass.
- The committed MySQL initial migration remains unapplied; deployment still requires explicit authorization, a reviewed target, and a backup/rollback plan.

---

## Unreleased — Product Schema and Model Foundation (Phase 4.1)

**Date:** 2026-08-10

### Summary

Implemented the complete Product request/query/response Schema layer plus the Product aggregate-root, ExperienceOption, ProductKit, and ProductImage Models as the first executable slices of Phase 4.1. This milestone freezes API data shapes and all four Product tables; it does **not** make Product endpoints available yet.

### Added

- `ProductType`, `ProductStatus`, and `DayType` as Python 3.10-compatible string Enums.
- Product validation constants for names, descriptions, prices, open positive experience dimensions, stock, image order, and search keywords.
- Strict JSON request Schemas for Product create/update, Experience Option CRUD input, image PATCH, Kit price/stock updates, and user/admin list queries.
- Response Schemas for user/admin lists, Experience/Kit details, create/update/status/delete actions, Options, images, dimensions, and Kit price/stock results.
- `LabeledValue[T]` for stable `{value, label}` response DTOs and `Page[T]` reuse for Product lists.
- Product Schema contract tests covering normal paths, invalid values, PATCH missing-vs-null semantics, field isolation, pagination nesting, and ORM/internal field filtering.
- Product aggregate-root Tortoise Model with string Enum fields, ORM validators, application and database defaults, a stable named status/deletion index, and real SQLite DDL tests.
- ExperienceOption Tortoise Model with a RESTRICT Product FK, open positive dimensions, DayType string Enum, strict Decimal price validation, logical deletion default, and a stable named all-history unique index.
- Reusable `UniqueIndex` and `StrictDecimalField` infrastructure for cross-database named uniqueness and pre-quantization Decimal precision validation.
- ExperienceOption Model contract tests covering ORM round trips, reverse relations, invalid boundaries, unknown Enums, logical-delete uniqueness, cross-Product scope, FK deletion protection, and real SQLite DDL.
- ProductKit Tortoise Model with a RESTRICT one-to-one Product relation, strict Decimal price, dual-layer stock default, non-negative stock validation, and parent-owned logical deletion.
- ProductKit Model contract tests covering reverse one-to-one access, price/stock boundaries, per-Product uniqueness, multiple independent Kit products, FK deletion protection, and real SQLite DDL.
- ProductImage Tortoise Model with Product RESTRICT and nullable ExperienceOption SET NULL relations, validated URL/sort fields, dual-layer defaults, logical deletion, and three stable named query indexes.
- ProductImage Model contract tests covering public/Option image relations, URL/sort boundaries, logical-delete preservation, Option physical-delete fallback, Product deletion protection, and real SQLite DDL.
- `asyncmy==0.2.11` as the required Tortoise ORM runtime driver for the production MySQL path.
- Integrated Product Model contract tests covering unified ORM registration, the complete forward/reverse relation graph, migration reconstruction of custom fields/indexes, exact SQLite named-index inventory, and offline MySQL DDL generation.
- Enterprise database migration runbook covering Aerich command boundaries, MySQL-authoritative SQL generation, review gates, existing-database baselines, backup/rollback requirements, and CHECK-constraint prerequisites.

### Changed

- Split Product Schemas by trust boundary: `app/schemas/product.py` owns requests/queries; `app/schemas/product_response.py` owns response allowlists.
- Product monetary requests accept plain decimal strings and convert to `Decimal`; responses require `Decimal` internally and serialize fixed two-place strings.
- Retired Product-specific `42211`–`42215`; static field and request-shape failures use global HTTP 422 validation. `42201` remains for database-dependent online readiness and `42221` for image file validation.
- Admin list/detail contracts now always return `is_deleted`; user responses never expose it.
- Experience duration and participants remain open positive integers rather than fixed Enums.
- Normalized the pending Product Model contract across business rules, API, database design, DBML, and coding standards: online Option writes require prior offline status, Kit stock is a Phase 4.1 final-value field, and Product string Enums use the Python 3.10-compatible `str, Enum` form.
- Replaced deprecated `BigIntField(pk=True)` with `BigIntField(primary_key=True)` in `BaseModel` and all documentation examples.
- Corrected the stale Kit pricing sentence in the business rules: price lives in `product_kits.price`, and online Product writes require prior offline status, matching the database and API contracts.
- Pinned pytest-asyncio's fixture loop scope to `function`, preserving per-test database isolation and preventing a future default change from silently altering test behavior.
- Replaced the hand-built MySQL URL with structured Tortoise credentials so reserved characters in database passwords cannot be misparsed as URL syntax, and added configuration contract tests.
- Corrected the Product relation-loading example to use the implemented `kit`, `experience_options`, and `images` reverse relation names; synchronized the documented/example application version with the v0.3.0 baseline.
- Added the missing database-level unique constraint for `users.phone`, matching the existing registration/update conflict contract and closing the concurrent-write gap left by Service pre-checks alone.
- Restored the documented User admin-list and AuditLog tracing indexes in their Models so the initial migration matches established query plans instead of silently omitting them.

### Important Decisions

1. **Strict write boundary.** Unknown JSON fields are rejected; body integers reject booleans, floats, and numeric strings.
2. **PATCH preserves intent.** Empty PATCH bodies are rejected, missing fields mean “unchanged,” and explicit null follows field-specific rules. Services must use `model_dump(exclude_unset=True)`.
3. **User/Admin output separation.** Online user responses require complete sellable shapes, while admin Draft responses allow empty images, Options, and dimensions.
4. **Response allowlists.** Out Schemas ignore undeclared internal attributes so relation IDs, deletion flags, type-specific fields, and sensitive data cannot leak across endpoints.
5. **Option identity is stable.** The named unique index excludes `is_deleted`, so `(product_id, duration, participants, day_type)` remains unique across all rows. Reposting a logically deleted combination must restore the same Option ID and update its current price instead of creating or physically deleting historical rows.
6. **Defaults exist at both boundaries.** Product `status` and `is_deleted` declare both ORM `default` and database `db_default`, so ORM and direct SQL inserts share the same defaults.
7. **Money is validated before ORM quantization.** Product price fields use `StrictDecimalField` because native Tortoise Decimal conversion can round extra fractional digits before ordinary validators run.
8. **Kit extension is one-to-one.** `ProductKit.product` uses `OneToOneField`, so the database allows at most one Kit row per Product and ORM reverse access is a single `product.kit` object rather than a collection.
9. **Kit lifecycle belongs to Product.** ProductKit has no independent `is_deleted`; Product logical deletion controls visibility while the RESTRICT FK prevents accidental physical deletion of the parent.
10. **Phase 4.1 stock is a final value.** `product_kits.stock` is stored and validated now, but inventory ledgers, automatic deduction/restoration, and concurrency control remain Phase 4.3 concerns.
11. **Image ownership has two levels.** A null `experience_option_id` represents a Product public image; a non-null value represents an Option image while retaining the mandatory Product FK for direct Product queries.
12. **Option physical deletion is a fallback path.** ProductImage uses SET NULL for its nullable Option FK so an abnormal physical Option deletion preserves the image; normal business operations still logically delete Options.
13. **Cover consistency belongs to Service.** The three image indexes are non-unique query indexes. Service must enforce same-Product Option ownership, prevent Option covers, and switch the single Product cover inside a transaction.
14. **Both database paths are executable contracts.** SQLite integration tests exercise real tables, while offline MySQL schema generation verifies production DDL without requiring or mutating a live MySQL instance.
15. **Schema generation is environment-gated.** Application startup may auto-create tables only in local development. Tests own disposable schemas, while production must use reviewed migrations and cannot mutate schema as a startup side effect.
16. **Integrity has explicit enforcement layers.** Structural constraints live in the database, value ranges are currently enforced by Schema/Model validation, and cross-row/cross-table invariants belong to Service/Validator. Database CHECK constraints remain a migration-review decision rather than an implicit claim.
17. **Production migrations are MySQL-authoritative.** Aerich stores dialect-specific raw SQL, so MySQL generates and reviews deployable migrations; SQLite remains a development/test compatibility target and does not supply SQL for MySQL releases.
18. **The initial migration fails on schema drift.** Reviewed MySQL DDL omits `IF NOT EXISTS`, runs outside a claimed transaction, and has an intentionally non-destructive empty downgrade instead of dropping every user and business table.

### Database

All four Product Models now declare `products`, `experience_options`, `product_kits`, and `product_images`, including RESTRICT/SET NULL relations, Option uniqueness, Kit one-to-one uniqueness, dual defaults, and stable query indexes. Real SQLite DDL and offline MySQL DDL generation both pass their contracts. A MySQL 8+ initial migration has been generated and statically reviewed offline; it has not been applied to any database.

### Known Limitations

- Validator, Service, API routes, upload handling, and business exceptions remain pending.
- Product API documentation remains Draft until those layers are implemented and endpoint integration tests pass.
- FastAPI `RequestValidationError` still needs global envelope verification/handling during API integration; direct Schema tests do not prove the HTTP 422 response body contract.
- Shared audit-log listing (`AuditLogService.list_logs` / `AuditLogOut`) is not part of Product Schema and remains pending.
- The MySQL initial migration is committed but unapplied. Production startup does not auto-create tables; deployment still requires a separately authorized migration execution against a reviewed target and backup plan.
- Positive/range rules are not yet duplicated as physical database `CHECK` constraints; direct SQL can bypass Schema/Model validators and must remain a controlled operational path.

---

## v0.3.0 — RBAC + Audit Logging + Product Module Design

**Date:** 2026-07-30

### Summary

Added role-based access control (RBAC) with permission cascading, admin user
management with paginated listing and disable, sequential audit logging for
all sensitive operations, and completed Product module design (Phase 4.1).

### Added

- **RBAC Depends chain:** `get_current_user` → `get_current_admin` → `get_current_super_admin`
- **Admin API (`/api/v1/admin/`):** paginated user list (filterable by status/role),
  disable user endpoint (with role hierarchy protection)
- **Audit logging:** `AuditLog` model tracking operator_id, action, target_type,
  target_id, description, ip_address. Sequential (non-fire-and-forget) writes for
  register, login, disable_user. Failed operations produce no audit log.
- **Client IP detection:** `get_client_ip()` with X-Forwarded-For support for
  proxy environments.
- **Page[T] generic** for consistent paginated responses (items, total, page,
  page_size, pages)
- **Product Business Rules (`docs/01_requirements/product_business_rules.md`):**
  complete domain model (Product 1→N ExperienceOption), aggregate rules,
  lifecycle, constraints, and design decisions for Phase 4.1.
- **ER diagram redesign:** `product_experiences` → `experience_options` (1:N),
  price separation, `sort` field, `is_deleted`, `audit_logs` table,
  `ON DELETE RESTRICT` FK constraints.

### Changed

- PATCH semantics for `/users/me` (partial update) instead of PUT
- Phone field now required on `UserCreate` and User model

### Database

**New table:** `audit_logs`

| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT PK | |
| operator_id | BIGINT FK | Who performed the action |
| action | VARCHAR(50) | REGISTER, LOGIN, DISABLE_USER |
| target_type | VARCHAR(50) | user |
| target_id | BIGINT | Affected entity |
| description | VARCHAR(256) | nullable |
| ip_address | VARCHAR(45) | IPv4/IPv6 |
| created_at | DATETIME | auto |

### Important Decisions

1. **Sequential audit logging.** Audit writes are awaited inline, not
   fire-and-forget. If the audit log fails, the operation fails — no silent
   audit gaps.

2. **Guard before log.** Audit logs are only written after the business
   operation succeeds. Failed disables produce no audit entry.

3. **Depends chain for RBAC.** Each permission level wraps the previous one,
   reusing `get_current_user` → `get_current_admin` → `get_current_super_admin`.
   No repeated token parsing, clean extensibility.

### Known Limitations

- No refresh token rotation (Phase 4)
- No rate limiting on login/register
- Product module: design complete, implementation pending (Phase 4.1)
- No email verification
- No OAuth / third-party login
- Admin enable user endpoint deferred
- Avatar upload deferred

---

## v0.2.0 — User Authentication System

**Date:** 2026-07-25

### Summary

Implemented the complete user authentication system, covering the full
layered architecture from Model to API. Users can now register, login
with JWT, view their profile, and change their password.

### Added

**API Endpoints**

| Method | URI | Auth | Description |
|--------|-----|------|-------------|
| POST | `/api/v1/auth/register` | No | User registration |
| POST | `/api/v1/auth/login` | No | Login, returns access + refresh tokens |
| POST | `/api/v1/auth/refresh` | No | Exchange refresh for new access token |
| POST | `/api/v1/auth/logout` | Bearer | Revoke refresh token |
| GET | `/api/v1/users/me` | Bearer | Get current user |
| PATCH | `/api/v1/users/me` | Bearer | Update profile |
| PUT | `/api/v1/users/me/password` | Bearer | Change password |
| GET | `/api/v1/admin/users` | Bearer (ADMIN+) | List users (paginated, filtered) |
| PUT | `/api/v1/admin/users/{id}/disable` | Bearer (ADMIN+) | Disable user |
| GET | `/api/v1/admin/config` | Bearer (SUPER_ADMIN) | System config |

**Models**

| Model | Table | Fields |
|-------|-------|--------|
| `BaseModel` | (abstract) | id, created_at, updated_at |
| `User` | users | username, password (hashed), nickname, phone, avatar, role, status, last_login_at |

**Enums**

| Enum | Values |
|------|--------|
| `UserRole` | USER (1), ADMIN (2), SUPER_ADMIN (3) |
| `UserStatus` | NORMAL (1), DISABLED (2) |

**Schemas (schemas/user.py)**

| Schema | Purpose |
|--------|---------|
| `UserCreate` | Registration request |
| `UserUpdate` | Profile update (nickname, phone, avatar) |
| `PasswordChange` | Password change request |
| `UserOut` | Full user detail response |
| `UserListItem` | Lightweight list item |

**Schemas (schemas/auth.py)**

| Schema | Purpose |
|--------|---------|
| `LoginRequest` | Login request |
| `TokenOut` | Login response — access + refresh tokens + user |
| `RefreshRequest` | Refresh token exchange request |
| `RefreshOut` | Refresh response — new access token only |

**Exceptions (app/common/exceptions/user.py)**

7 named exception classes: `UsernameAlreadyExists` (1001), `UserNotFound` (1002),
`IncorrectPassword` (1003), `OldPasswordIncorrect` (1004), `UserDisabled` (1005),
`TokenExpired` (1006), `PhoneAlreadyExists` (1007).

**Infrastructure**

| Component | File |
|-----------|------|
| Configuration | `app/core/config.py` — 14 fields via pydantic-settings |
| Security | `app/core/security.py` — bcrypt + JWT (HS256, jti, type validation) |
| Redis | `app/core/redis.py` — Refresh token store (rt:{jti}) |
| Logging | `app/core/logging.py` — DEBUG/INFO env-aware |
| Database | `app/db/database.py` — register_tortoise (SQLite/MySQL) |
| DI | `app/api/deps.py` — get_current_user / admin / super_admin Depends chain |
| Pagination | `app/common/pagination.py` — PageParams + Page[T] |
| RBAC | `app/api/v1/admin_users.py` — paginated user list + disable |
| Audit | `app/models/audit_log.py` — operator_id, action, target_type, ip |
| Tests | `tests/` — 38 tests covering all endpoints |

### Changed

- **Exception handling:** Replaced single catch-all handler with per-type
  registration to fix Starlette re-raise issue.
- **Response format:** All endpoints now use `success()` envelope instead of
  `response_model` — ensures 100% consistent `{"code":0, "data":...}` format.
- **API layer:** Removed `response_model` decorators; `UserOut.model_validate()`
  handles serialization and password exclusion.

### Database

**New table:** `users`

| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT PK | |
| username | VARCHAR(32) UNIQUE | |
| password | VARCHAR(128) | bcrypt hashed |
| nickname | VARCHAR(32) | |
| phone | VARCHAR(11) | nullable |
| avatar | VARCHAR(256) | nullable |
| role | SMALLINT | default 1 |
| status | SMALLINT | default 1 |
| last_login_at | DATETIME | nullable |
| created_at | DATETIME | auto |
| updated_at | DATETIME | auto |

### Important Decisions

1. **JWT over sessions.** RESTful, no server-side state, suitable for
   separated frontend/backend. See architecture.md §6.3.

2. **Service layer owns business logic.** Repository is pure data access,
   all checks (dedup, password verification, status validation) live in
   `UserService`. This keeps the API layer thin and testable.

3. **Named exceptions over generic codes.** `raise UsernameAlreadyExists()`
   instead of `raise BusinessException(code=1001, ...)`. Self-documenting,
   impossible to get the wrong code number.

4. **pydantic-settings over os.getenv().** Automatic type coercion (bool,
   int from .env strings), field validation at startup, cleaner code.

5. **`success()` envelope over `response_model`.** The `{"code":0,
   "data":...}` format is enforced at the API layer, not delegated to
   FastAPI serialization. This prevents mixed response formats.

6. **`field_serializer` for IntEnum.** Stored as TINYINT in DB, exposed
   as lowercase string in API (`"user"` not `1`). This matches the
   API design conventions.

### Known Limitations

- No refresh token rotation (Phase 4)
- No login audit log
- No rate limiting on login/register
- No email verification
- No OAuth / third-party login
- Admin enable user endpoint deferred to Phase 3
- Avatar upload deferred to Phase 3

### Dependencies Added

| Package | Version | Purpose |
|---------|---------|---------|
| pydantic-settings | 2.14 | Configuration management |
| passlib[bcrypt] | 1.7.4 | Password hashing |
| python-jose[cryptography] | 3.3.0 | JWT signing/verification |
| tzdata | — | Timezone data (Windows) |
| pytest | 9.1 | Test framework |
| pytest-asyncio | 1.4 | Async test support |
| httpx | — | HTTP test client |

---

## v0.1.0 — Project Bootstrap

**Date:** 2026-07-24

### Summary

Project initialized with FastAPI skeleton, configuration system, logging,
exception handling, and database connection. No business logic.

### Added

- FastAPI application with lifespan (startup/shutdown lifecycle)
- pydantic-settings configuration with .env / .env.example
- Structured logging (DEBUG/INFO env-aware)
- AppException hierarchy with 4 HTTP-mapped types
- Tortoise ORM with SQLite/MySQL auto-switch
- BaseModel with id, created_at, updated_at
- Unified response envelope (`success()` / `error()`)
- Health check endpoint

### Known Limitations

- No business modules
- No authentication
- No tests
