# Development Changelog

> 每个独立功能模块完成后更新。记录做了什么、为什么这样做、有什么限制。

---

## Unreleased — Product Schema Foundation (Phase 4.1)

**Date:** 2026-08-09

### Summary

Implemented the complete Product request, query, and response Schema layer as the first executable slice of Phase 4.1. This milestone freezes API data shapes and validation boundaries; it does **not** make Product endpoints available yet.

### Added

- `ProductType`, `ProductStatus`, and `DayType` as Python 3.10-compatible string Enums.
- Product validation constants for names, descriptions, prices, open positive experience dimensions, stock, image order, and search keywords.
- Strict JSON request Schemas for Product create/update, Experience Option CRUD input, image PATCH, Kit price/stock updates, and user/admin list queries.
- Response Schemas for user/admin lists, Experience/Kit details, create/update/status/delete actions, Options, images, dimensions, and Kit price/stock results.
- `LabeledValue[T]` for stable `{value, label}` response DTOs and `Page[T]` reuse for Product lists.
- Product Schema contract tests covering normal paths, invalid values, PATCH missing-vs-null semantics, field isolation, pagination nesting, and ORM/internal field filtering.

### Changed

- Split Product Schemas by trust boundary: `app/schemas/product.py` owns requests/queries; `app/schemas/product_response.py` owns response allowlists.
- Product monetary requests accept plain decimal strings and convert to `Decimal`; responses require `Decimal` internally and serialize fixed two-place strings.
- Retired Product-specific `42211`–`42215`; static field and request-shape failures use global HTTP 422 validation. `42201` remains for database-dependent online readiness and `42221` for image file validation.
- Admin list/detail contracts now always return `is_deleted`; user responses never expose it.
- Experience duration and participants remain open positive integers rather than fixed Enums.

### Important Decisions

1. **Strict write boundary.** Unknown JSON fields are rejected; body integers reject booleans, floats, and numeric strings.
2. **PATCH preserves intent.** Empty PATCH bodies are rejected, missing fields mean “unchanged,” and explicit null follows field-specific rules. Services must use `model_dump(exclude_unset=True)`.
3. **User/Admin output separation.** Online user responses require complete sellable shapes, while admin Draft responses allow empty images, Options, and dimensions.
4. **Response allowlists.** Out Schemas ignore undeclared internal attributes so relation IDs, deletion flags, type-specific fields, and sensitive data cannot leak across endpoints.

### Database

No database changes and no migration required.

### Known Limitations

- Product Model, Repository, Validator, Service, API routes, upload handling, and business exceptions remain pending.
- Product API documentation remains Draft until those layers are implemented and endpoint integration tests pass.
- FastAPI `RequestValidationError` still needs global envelope verification/handling during API integration; direct Schema tests do not prove the HTTP 422 response body contract.
- Shared audit-log listing (`AuditLogService.list_logs` / `AuditLogOut`) is not part of Product Schema and remains pending.

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
