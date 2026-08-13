"""Initial MySQL schema migration; generated offline and not portable to SQLite."""

from tortoise import BaseDBAsyncClient

# MySQL DDL has implicit-commit semantics; do not claim full transactional rollback.
RUN_IN_TRANSACTION = False


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE `audit_logs` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `operator_id` BIGINT NOT NULL,
    `action` VARCHAR(50) NOT NULL,
    `target_type` VARCHAR(50) NOT NULL,
    `target_id` BIGINT NOT NULL,
    `description` VARCHAR(256),
    `ip_address` VARCHAR(45) NOT NULL,
    KEY `idx_audit_target_created` (`target_type`, `target_id`, `created_at`),
    KEY `idx_audit_operator_created` (`operator_id`, `created_at`)
) CHARACTER SET utf8mb4 COMMENT='记录所有关键操作的审计日志。';
CREATE TABLE `products` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `product_type` VARCHAR(20) NOT NULL COMMENT 'EXPERIENCE: experience\nKIT: kit',
    `description` LONGTEXT,
    `status` VARCHAR(20) NOT NULL COMMENT 'DRAFT: draft\nONLINE: online\nOFFLINE: offline' DEFAULT 'draft',
    `is_deleted` BOOL NOT NULL DEFAULT 0,
    KEY `idx_products_status_deleted` (`status`, `is_deleted`)
) CHARACTER SET utf8mb4 COMMENT='体验商品与套装商品的公共聚合根。';
CREATE TABLE `experience_options` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `duration` INT NOT NULL,
    `participants` INT NOT NULL,
    `day_type` VARCHAR(20) NOT NULL COMMENT 'WEEKDAY: weekday\nHOLIDAY: holiday',
    `price` DECIMAL(10,2) NOT NULL,
    `is_deleted` BOOL NOT NULL DEFAULT 0,
    `product_id` BIGINT NOT NULL,
    CONSTRAINT `fk_experien_products_8b605ad8` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT,
    UNIQUE KEY `idx_option_unique` (`product_id`, `duration`, `participants`, `day_type`)
) CHARACTER SET utf8mb4 COMMENT='体验商品的一组时长、人数、日期类型与价格配置。';
CREATE TABLE `product_images` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `image_url` VARCHAR(2048) NOT NULL,
    `is_cover` BOOL NOT NULL DEFAULT 0,
    `sort` INT NOT NULL DEFAULT 0,
    `is_deleted` BOOL NOT NULL DEFAULT 0,
    `experience_option_id` BIGINT,
    `product_id` BIGINT NOT NULL,
    CONSTRAINT `fk_product__experien_1a7b23a0` FOREIGN KEY (`experience_option_id`) REFERENCES `experience_options` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_product__products_fa4c4954` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT,
    KEY `idx_image_product_sort` (`product_id`, `sort`),
    KEY `idx_image_product_cover` (`product_id`, `is_cover`),
    KEY `idx_image_option_sort` (`experience_option_id`, `sort`)
) CHARACTER SET utf8mb4 COMMENT='商品图片；可选关联 ExperienceOption 以表达 Option 专属图片。';
CREATE TABLE `product_kits` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `price` DECIMAL(10,2) NOT NULL,
    `stock` INT NOT NULL DEFAULT 0,
    `product_id` BIGINT NOT NULL UNIQUE,
    CONSTRAINT `fk_product__products_f9712c96` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT
) CHARACTER SET utf8mb4 COMMENT='套装商品的价格与当前库存。';
CREATE TABLE `users` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `username` VARCHAR(32) NOT NULL UNIQUE,
    `password` VARCHAR(128) NOT NULL,
    `nickname` VARCHAR(32) NOT NULL,
    `phone` VARCHAR(11) NOT NULL UNIQUE,
    `avatar` VARCHAR(256),
    `role` SMALLINT NOT NULL,
    `status` SMALLINT NOT NULL,
    `last_login_at` DATETIME(6),
    KEY `idx_users_status_role` (`status`, `role`)
) CHARACTER SET utf8mb4 COMMENT='平台用户。';
CREATE TABLE `aerich` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `version` VARCHAR(255) NOT NULL,
    `app` VARCHAR(100) NOT NULL,
    `content` JSON NOT NULL
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    # The initial downgrade is intentionally non-destructive: dropping every table
    # would erase user and business data instead of providing a safe rollback.
    return ""


MODELS_STATE = (
    "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"
)
