from tortoise import BaseDBAsyncClient

# MySQL DDL implicitly commits; this migration cannot promise atomic rollback.
RUN_IN_TRANSACTION = False


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `product_kits`
            MODIFY COLUMN `stock` INT NULL DEFAULT 0,
            ADD COLUMN `kit_kind` VARCHAR(20) NOT NULL COMMENT 'FIXED: fixed\nCOLOR_SELECTABLE: color_selectable' DEFAULT 'fixed',
            ADD COLUMN `sale_unit_grams` SMALLINT NULL;
        CREATE TABLE `bead_colors` (
            `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
            `created_at` DATETIME(6) NOT NULL,
            `updated_at` DATETIME(6) NOT NULL,
            `slot_no` SMALLINT NOT NULL,
            `color_code` VARCHAR(50),
            `name` VARCHAR(100),
            `swatch_image_url` VARCHAR(2048),
            `sort` SMALLINT NOT NULL DEFAULT 0,
            `is_active` BOOL NOT NULL DEFAULT 0,
            CONSTRAINT `ck_bead_colors_sort_range`
                CHECK (`sort` BETWEEN 0 AND 32767),
            UNIQUE KEY `uidx_bead_colors_slot_no` (`slot_no`),
            UNIQUE KEY `uidx_bead_colors_color_code` (`color_code`),
            KEY `idx_bead_colors_active_sort_slot` (`is_active`, `sort`, `slot_no`)
        ) CHARACTER SET utf8mb4 COMMENT='全局固定 221 槽的拼豆颜色目录；占位槽允许未配置。';
        INSERT INTO `bead_colors` (
            `created_at`, `updated_at`, `slot_no`, `color_code`, `name`,
            `swatch_image_url`, `sort`, `is_active`
        )
        SELECT
            CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6), numbers.slot_no,
            NULL, NULL, NULL, numbers.slot_no, 0
        FROM (
            SELECT ones.n + tens.n * 10 + hundreds.n * 100 + 1 AS slot_no
            FROM (
                SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2
                UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
                UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
                UNION ALL SELECT 9
            ) AS ones
            CROSS JOIN (
                SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2
                UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
                UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
                UNION ALL SELECT 9
            ) AS tens
            CROSS JOIN (
                SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2
            ) AS hundreds
        ) AS numbers
        WHERE numbers.slot_no BETWEEN 1 AND 221
        ORDER BY numbers.slot_no;
        CREATE TABLE `product_kit_colors` (
            `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
            `created_at` DATETIME(6) NOT NULL,
            `updated_at` DATETIME(6) NOT NULL,
            `is_enabled` BOOL NOT NULL DEFAULT 0,
            `stock_units` INT NOT NULL DEFAULT 0,
            `bead_color_id` BIGINT NOT NULL,
            `product_id` BIGINT NOT NULL,
            CONSTRAINT `fk_product_kit_colors_bead_color`
                FOREIGN KEY (`bead_color_id`) REFERENCES `bead_colors` (`id`)
                ON DELETE RESTRICT,
            CONSTRAINT `fk_product_kit_colors_product`
                FOREIGN KEY (`product_id`) REFERENCES `products` (`id`)
                ON DELETE RESTRICT,
            UNIQUE KEY `uidx_product_kit_colors_product_color`
                (`product_id`, `bead_color_id`),
            KEY `idx_product_kit_colors_product_enabled`
                (`product_id`, `is_enabled`),
            KEY `idx_product_kit_colors_color_enabled`
                (`bead_color_id`, `is_enabled`)
        ) CHARACTER SET utf8mb4 COMMENT='自选颜色 Kit 的商品级启用状态与 10g 单位库存余额。';
        ALTER TABLE `order_items`
            ADD COLUMN `kit_color_id` BIGINT NULL,
            ADD COLUMN `kit_color_slot_no` SMALLINT NULL,
            ADD COLUMN `kit_color_code` VARCHAR(50) NULL,
            ADD COLUMN `kit_color_name` VARCHAR(100) NULL,
            ADD COLUMN `sale_unit_grams` SMALLINT NULL,
            ADD CONSTRAINT `fk_order_items_kit_color`
                FOREIGN KEY (`kit_color_id`) REFERENCES `product_kit_colors` (`id`)
                ON DELETE RESTRICT;
        ALTER TABLE `inventory_transactions`
            ADD COLUMN `kit_color_id` BIGINT NULL,
            ADD CONSTRAINT `fk_inventory_transactions_kit_color`
                FOREIGN KEY (`kit_color_id`) REFERENCES `product_kit_colors` (`id`)
                ON DELETE RESTRICT,
            ADD KEY `idx_inventory_color_created_id`
                (`kit_color_id`, `created_at`, `id`);
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    # This removes color-level inventory configuration and converts any
    # color-selectable parent balance back to the legacy zero-stock shape.
    return """
        ALTER TABLE `inventory_transactions`
            DROP FOREIGN KEY `fk_inventory_transactions_kit_color`,
            DROP INDEX `idx_inventory_color_created_id`,
            DROP COLUMN `kit_color_id`;
        ALTER TABLE `order_items`
            DROP FOREIGN KEY `fk_order_items_kit_color`,
            DROP COLUMN `sale_unit_grams`,
            DROP COLUMN `kit_color_name`,
            DROP COLUMN `kit_color_code`,
            DROP COLUMN `kit_color_slot_no`,
            DROP COLUMN `kit_color_id`;
        DROP TABLE `product_kit_colors`;
        DROP TABLE `bead_colors`;
        UPDATE `product_kits` SET `stock` = 0 WHERE `stock` IS NULL;
        ALTER TABLE `product_kits`
            MODIFY COLUMN `stock` INT NOT NULL DEFAULT 0,
            DROP COLUMN `sale_unit_grams`,
            DROP COLUMN `kit_kind`;
    """


# Replaced with the complete post-M6 model snapshot after all Product,
# Order and Inventory model changes in this shared migration are finalized.
MODELS_STATE = "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"
