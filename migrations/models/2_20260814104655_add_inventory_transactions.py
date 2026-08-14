"""Add Inventory ledger and opening balances with reviewed MySQL 8+ SQL."""

from tortoise import BaseDBAsyncClient

# MySQL DDL implicitly commits. The opening-balance INSERT therefore requires a
# maintenance window and verified backup; this file must not claim atomic DDL+DML.
RUN_IN_TRANSACTION = False


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE `inventory_transactions` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `transaction_type` VARCHAR(40) NOT NULL COMMENT 'OPENING_BALANCE: opening_balance\nADMIN_ADJUSTMENT: admin_adjustment\nORDER_DEDUCTION: order_deduction\nORDER_CANCELLATION_RESTORE: order_cancellation_restore',
    `change_quantity` INT NOT NULL,
    `before_quantity` INT NOT NULL,
    `after_quantity` INT NOT NULL,
    `source_type` VARCHAR(30) NOT NULL COMMENT 'MIGRATION: migration\nADMIN: admin\nORDER: order',
    `source_id` BIGINT,
    `reason` VARCHAR(256) NOT NULL,
    `idempotency_key` VARCHAR(256) NOT NULL,
    `operator_id` BIGINT,
    `product_id` BIGINT NOT NULL,
    CONSTRAINT `fk_inventor_users_b3a47565` FOREIGN KEY (`operator_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_inventor_products_daeaf291` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT,
    UNIQUE KEY `uidx_inventory_idempotency_key` (`idempotency_key`),
    KEY `idx_inventory_product_created_id` (`product_id`, `created_at`, `id`),
    KEY `idx_inventory_source_created_id` (`source_type`, `source_id`, `created_at`, `id`),
    KEY `idx_inventory_type_created_id` (`transaction_type`, `created_at`, `id`),
    KEY `idx_inventory_created_id` (`created_at`, `id`)
) CHARACTER SET utf8mb4 COMMENT='记录每一次已提交库存变化；当前余额仍以 ProductKit.stock 为准。';

        INSERT INTO `inventory_transactions` (
            `created_at`,
            `updated_at`,
            `transaction_type`,
            `change_quantity`,
            `before_quantity`,
            `after_quantity`,
            `source_type`,
            `source_id`,
            `reason`,
            `idempotency_key`,
            `operator_id`,
            `product_id`
        )
        SELECT
            UTC_TIMESTAMP(6),
            UTC_TIMESTAMP(6),
            'opening_balance',
            `product_kits`.`stock`,
            0,
            `product_kits`.`stock`,
            'migration',
            NULL,
            'Inventory opening balance migration',
            CONCAT('inventory:opening:product:', `product_kits`.`product_id`),
            NULL,
            `product_kits`.`product_id`
        FROM `product_kits`
        WHERE `product_kits`.`stock` > 0
        ORDER BY `product_kits`.`product_id`;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    # This rollback deletes opening balances and every later Inventory business
    # event without reconstructing ProductKit.stock. Execute only after explicit
    # approval, a verified backup, and confirmation that the runtime is stopped.
    return """
        DROP TABLE IF EXISTS `inventory_transactions`;"""


MODELS_STATE = (
    "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"
    "oVy+WuyaapyehY0MDVoU7eQw+zn/8HeceBvw=="
)
