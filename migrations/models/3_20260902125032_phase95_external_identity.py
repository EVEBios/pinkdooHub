from tortoise import BaseDBAsyncClient

# MySQL DDL implicitly commits. Apply only in a maintenance window after a
# verified backup; do not claim atomic rollback across these statements.
RUN_IN_TRANSACTION = False


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE `external_identities` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `provider` VARCHAR(32) NOT NULL,
    `app_id` VARCHAR(64) NOT NULL,
    `subject_id` VARCHAR(128) NOT NULL,
    `union_id` VARCHAR(128),
    `user_id` BIGINT NOT NULL,
    CONSTRAINT `fk_external_users_28096dfa` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
    UNIQUE KEY `uidx_external_identity_subject` (`provider`, `app_id`, `subject_id`),
    UNIQUE KEY `uidx_external_identity_union` (`provider`, `union_id`),
    KEY `idx_external_identity_user_provider` (`user_id`, `provider`, `created_at`)
) CHARACTER SET utf8mb4 COMMENT='用户与外部平台主体的绑定。';
        ALTER TABLE `users` ADD `auth_version` INT NOT NULL DEFAULT 0;
        ALTER TABLE `users` ADD `deleted_at` DATETIME(6);
        ALTER TABLE `users` MODIFY COLUMN `phone` VARCHAR(11);
        ALTER TABLE `users` MODIFY COLUMN `password` VARCHAR(128);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    # Downgrade is destructive and requires every retained User to have a
    # non-NULL phone/password again. External identities are deleted first.
    return """
        DROP TABLE IF EXISTS `external_identities`;
        ALTER TABLE `users` DROP COLUMN `auth_version`;
        ALTER TABLE `users` DROP COLUMN `deleted_at`;
        ALTER TABLE `users` MODIFY COLUMN `phone` VARCHAR(11) NOT NULL;
        ALTER TABLE `users` MODIFY COLUMN `password` VARCHAR(128) NOT NULL;"""


MODELS_STATE = (
    "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"
)
