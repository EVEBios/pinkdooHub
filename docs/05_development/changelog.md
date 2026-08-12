# Development Changelog

> 每个独立功能模块完成后更新。记录做了什么、为什么这样做、有什么限制。

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
