from tortoise import BaseDBAsyncClient

# MySQL DDL implicitly commits; this migration cannot promise atomic rollback.
RUN_IN_TRANSACTION = False


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE `reservation_settings` (
            `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
            `created_at` DATETIME(6) NOT NULL,
            `updated_at` DATETIME(6) NOT NULL,
            `singleton_key` BOOL NOT NULL DEFAULT 1,
            `weekly_closed_weekday` VARCHAR(32) NOT NULL DEFAULT 'monday',
            CONSTRAINT `ck_reservation_settings_singleton`
                CHECK (`singleton_key` = 1),
            UNIQUE KEY `uidx_reservation_settings_singleton` (`singleton_key`)
        ) CHARACTER SET utf8mb4 COMMENT='预约日历的全店单例设置';
        INSERT INTO `reservation_settings` (
            `created_at`, `updated_at`, `singleton_key`,
            `weekly_closed_weekday`
        ) VALUES (CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6), 1, 'monday');
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE `reservation_settings`;
    """
