from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = False  # MySQL DDL 会隐式提交，不宣称整笔可回滚。


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `store_bead_stocks` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `packs` INT NOT NULL,
    `revision` INT NOT NULL,
    `bead_color_id` BIGINT NOT NULL UNIQUE,
    CONSTRAINT `fk_store_be_bead_col_28acc684` FOREIGN KEY (`bead_color_id`) REFERENCES `bead_colors` (`id`) ON DELETE RESTRICT
) CHARACTER SET utf8mb4;
        CREATE TABLE IF NOT EXISTS `store_bead_stock_batches` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `request_key` VARCHAR(36) NOT NULL,
    `fingerprint` VARCHAR(64) NOT NULL,
    `reason` VARCHAR(20) NOT NULL,
    `note` VARCHAR(500) NOT NULL,
    `operator_id` BIGINT NOT NULL,
    CONSTRAINT `fk_store_be_users_01e284b4` FOREIGN KEY (`operator_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
    UNIQUE KEY `uidx_store_bead_batch_request` (`operator_id`, `request_key`),
    KEY `idx_store_bead_batch_time` (`created_at`, `id`)
) CHARACTER SET utf8mb4;
        CREATE TABLE IF NOT EXISTS `store_bead_stock_entries` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `slot_no` SMALLINT NOT NULL,
    `color_code` VARCHAR(50),
    `color_name` VARCHAR(100),
    `before_packs` INT,
    `after_packs` INT NOT NULL,
    `revision` INT NOT NULL,
    `batch_id` BIGINT NOT NULL,
    `bead_color_id` BIGINT NOT NULL,
    CONSTRAINT `fk_store_be_store_be_a906d165` FOREIGN KEY (`batch_id`) REFERENCES `store_bead_stock_batches` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_store_be_bead_col_99771157` FOREIGN KEY (`bead_color_id`) REFERENCES `bead_colors` (`id`) ON DELETE RESTRICT,
    UNIQUE KEY `uidx_store_bead_entry_batch` (`batch_id`, `bead_color_id`),
    UNIQUE KEY `uidx_store_bead_entry_revision` (`bead_color_id`, `revision`)
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    for table in ("store_bead_stock_entries", "store_bead_stock_batches", "store_bead_stocks"):
        rows = await db.execute_query_dict(f"SELECT COUNT(*) AS total FROM `{table}`")
        if rows[0]["total"]:
            raise RuntimeError("Cannot downgrade store bead stock with persisted inventory/history")
    return """
        DROP TABLE IF EXISTS `store_bead_stock_entries`;
        DROP TABLE IF EXISTS `store_bead_stock_batches`;
        DROP TABLE IF EXISTS `store_bead_stocks`;"""


MODELS_STATE = (
    "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"
    "oD/iFg=="
)
