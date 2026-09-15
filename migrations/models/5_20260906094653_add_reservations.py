from tortoise import BaseDBAsyncClient

# MySQL DDL implicitly commits; this migration cannot promise atomic rollback.
RUN_IN_TRANSACTION = False


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE `store_business_days` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `business_date` DATE NOT NULL,
    `is_closed` BOOL NOT NULL DEFAULT 0,
    UNIQUE KEY `uidx_store_business_day_date` (`business_date`)
) CHARACTER SET utf8mb4 COMMENT='预约创建与人工店休共用的一日一行并发锁点。';
        CREATE TABLE `reservations` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `scheduled_start_at` DATETIME(6) NOT NULL,
    `scheduled_end_at` DATETIME(6) NOT NULL,
    `product_name` VARCHAR(100) NOT NULL,
    `option_duration_minutes` INT NOT NULL,
    `option_participants` INT NOT NULL,
    `option_day_type` VARCHAR(20) NOT NULL COMMENT 'WEEKDAY: weekday\nHOLIDAY: holiday',
    `option_price` DECIMAL(10,2) NOT NULL,
    `status` VARCHAR(32) NOT NULL COMMENT 'PENDING: pending\nCONFIRMED: confirmed\nREJECTED: rejected\nCANCELLED: cancelled' DEFAULT 'pending',
    `rejection_reason` VARCHAR(32) COMMENT 'NO_CAPACITY: no_capacity',
    `cancellation_reason` VARCHAR(32) COMMENT 'CUSTOMER_REQUEST: customer_request\nSTORE_CLOSED: store_closed',
    `confirmed_at` DATETIME(6),
    `rejected_at` DATETIME(6),
    `cancelled_at` DATETIME(6),
    `business_day_id` BIGINT NOT NULL,
    `experience_option_id` BIGINT NOT NULL,
    `product_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    CONSTRAINT `fk_reservat_store_bu_6574c4bd` FOREIGN KEY (`business_day_id`) REFERENCES `store_business_days` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_reservat_experien_a8d80064` FOREIGN KEY (`experience_option_id`) REFERENCES `experience_options` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_reservat_products_c17f623b` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_reservat_users_69c5e4f3` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
    KEY `idx_reservations_user_start_id` (`user_id`, `scheduled_start_at`, `id`),
    KEY `idx_reservations_user_status_end_id` (`user_id`, `status`, `scheduled_end_at`, `id`),
    KEY `idx_reservations_user_status_start_id` (`user_id`, `status`, `scheduled_start_at`, `id`),
    KEY `idx_reservations_day_status_start_id` (`business_day_id`, `status`, `scheduled_start_at`, `id`),
    KEY `idx_reservations_status_start_id` (`status`, `scheduled_start_at`, `id`)
) CHARACTER SET utf8mb4 COMMENT='独立于 Order/Payment 的体验预约及不可变创建快照。';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    # This removes all Reservation and custom store-closure history. Once
    # runtime writes exist, prefer a reviewed forward fix and verified backup.
    return """
        DROP TABLE `reservations`;
        DROP TABLE `store_business_days`;"""


MODELS_STATE = (
    "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"
    "Pre98jezX/8PKKpywA=="
)
