from tortoise import BaseDBAsyncClient

# MySQL DDL implicitly commits; this migration cannot promise atomic rollback.
RUN_IN_TRANSACTION = False


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE `store_tables` (
            `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
            `created_at` DATETIME(6) NOT NULL,
            `updated_at` DATETIME(6) NOT NULL,
            `table_no` VARCHAR(3) NOT NULL,
            `display_name` VARCHAR(50) NOT NULL,
            `qr_token` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
            `is_enabled` BOOL NOT NULL DEFAULT 1,
            UNIQUE KEY `uidx_store_table_no` (`table_no`),
            UNIQUE KEY `uidx_store_table_qr_token` (`qr_token`)
        ) CHARACTER SET utf8mb4 COMMENT='门店固定桌台及公开二维码定位符';

        CREATE TABLE `table_sessions` (
            `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
            `created_at` DATETIME(6) NOT NULL,
            `updated_at` DATETIME(6) NOT NULL,
            `session_no` VARCHAR(28) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
            `table_id` BIGINT NOT NULL,
            `user_id` BIGINT NOT NULL,
            `order_id` BIGINT NOT NULL,
            `payment_id` BIGINT NULL,
            `status` VARCHAR(32) NOT NULL DEFAULT 'awaiting_payment',
            `claim_idempotency_key` VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
            `claim_request_fingerprint` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
            `release_idempotency_key` VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL,
            `claimed_at` DATETIME(6) NOT NULL,
            `payment_deadline_at` DATETIME(6) NOT NULL,
            `started_at` DATETIME(6) NULL,
            `table_release_at` DATETIME(6) NULL,
            `closed_at` DATETIME(6) NULL,
            `close_reason` VARCHAR(32) NULL,
            `closed_by_user_id` BIGINT NULL,
            `admin_close_reason` VARCHAR(200) NULL,
            UNIQUE KEY `uidx_table_session_no` (`session_no`),
            UNIQUE KEY `uidx_table_session_claim_idempotency` (`claim_idempotency_key`),
            UNIQUE KEY `uidx_table_session_release_idempotency` (`release_idempotency_key`),
            UNIQUE KEY `uidx_table_session_payment` (`payment_id`),
            KEY `idx_table_session_table_claimed_id` (`table_id`, `claimed_at`, `id`),
            KEY `idx_table_session_user_status_claimed_id` (`user_id`, `status`, `claimed_at`, `id`),
            KEY `idx_table_session_order_status_claimed_id` (`order_id`, `status`, `claimed_at`, `id`),
            KEY `idx_table_session_status_payment_deadline_id` (`status`, `payment_deadline_at`, `id`),
            KEY `idx_table_session_status_release_id` (`status`, `table_release_at`, `id`),
            CONSTRAINT `fk_table_sessions_table`
                FOREIGN KEY (`table_id`) REFERENCES `store_tables` (`id`) ON DELETE RESTRICT,
            CONSTRAINT `fk_table_sessions_user`
                FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
            CONSTRAINT `fk_table_sessions_order`
                FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`) ON DELETE RESTRICT,
            CONSTRAINT `fk_table_sessions_payment`
                FOREIGN KEY (`payment_id`) REFERENCES `payments` (`id`) ON DELETE RESTRICT,
            CONSTRAINT `fk_table_sessions_closed_by`
                FOREIGN KEY (`closed_by_user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT
        ) CHARACTER SET utf8mb4 COMMENT='二维码开台生命周期';

        CREATE TABLE `table_session_timers` (
            `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
            `created_at` DATETIME(6) NOT NULL,
            `updated_at` DATETIME(6) NOT NULL,
            `session_id` BIGINT NOT NULL,
            `duration_minutes` INT NOT NULL,
            `buffer_minutes` SMALLINT NOT NULL DEFAULT 10,
            `started_at` DATETIME(6) NOT NULL,
            `service_ends_at` DATETIME(6) NOT NULL,
            `grace_ends_at` DATETIME(6) NOT NULL,
            UNIQUE KEY `uidx_table_session_timer_duration` (`session_id`, `duration_minutes`),
            CONSTRAINT `fk_table_session_timers_session`
                FOREIGN KEY (`session_id`) REFERENCES `table_sessions` (`id`) ON DELETE RESTRICT
        ) CHARACTER SET utf8mb4 COMMENT='桌台会话分组计时快照';

        CREATE TABLE `table_occupancies` (
            `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
            `created_at` DATETIME(6) NOT NULL,
            `updated_at` DATETIME(6) NOT NULL,
            `table_id` BIGINT NOT NULL,
            `session_id` BIGINT NOT NULL,
            `user_id` BIGINT NOT NULL,
            `order_id` BIGINT NOT NULL,
            UNIQUE KEY `uidx_table_occupancy_table` (`table_id`),
            UNIQUE KEY `uidx_table_occupancy_session` (`session_id`),
            UNIQUE KEY `uidx_table_occupancy_user` (`user_id`),
            UNIQUE KEY `uidx_table_occupancy_order` (`order_id`),
            CONSTRAINT `fk_table_occupancies_table`
                FOREIGN KEY (`table_id`) REFERENCES `store_tables` (`id`) ON DELETE RESTRICT,
            CONSTRAINT `fk_table_occupancies_session`
                FOREIGN KEY (`session_id`) REFERENCES `table_sessions` (`id`) ON DELETE RESTRICT,
            CONSTRAINT `fk_table_occupancies_user`
                FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
            CONSTRAINT `fk_table_occupancies_order`
                FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`) ON DELETE RESTRICT
        ) CHARACTER SET utf8mb4 COMMENT='当前桌台占用唯一性物化';
    """

async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE `table_occupancies`;
        DROP TABLE `table_session_timers`;
        DROP TABLE `table_sessions`;
        DROP TABLE `store_tables`;
    """
