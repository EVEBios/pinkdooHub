"""Add Order tables with reviewed MySQL 8+ DDL; generated offline."""

from tortoise import BaseDBAsyncClient

# MySQL DDL has implicit-commit semantics; do not claim transactional rollback.
RUN_IN_TRANSACTION = False


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE `orders` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `order_no` VARCHAR(28) NOT NULL UNIQUE,
    `total_amount` DECIMAL(10,2) NOT NULL,
    `status` SMALLINT NOT NULL DEFAULT 0,
    `remark` VARCHAR(500),
    `user_id` BIGINT NOT NULL,
    CONSTRAINT `fk_orders_users_411bb784` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
    KEY `idx_orders_user_created_id` (`user_id`, `created_at`, `id`),
    KEY `idx_orders_user_status_created_id` (`user_id`, `status`, `created_at`, `id`),
    KEY `idx_orders_status_created_id` (`status`, `created_at`, `id`),
    KEY `idx_orders_created_id` (`created_at`, `id`)
) CHARACTER SET utf8mb4 COMMENT='订单聚合根；金额与状态只允许由 Order Service 编排修改。';
        CREATE TABLE `order_items` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `option_duration_minutes` INT,
    `option_participants` INT,
    `option_day_type` VARCHAR(20) COMMENT 'WEEKDAY: weekday\nHOLIDAY: holiday',
    `product_name` VARCHAR(100) NOT NULL,
    `product_price` DECIMAL(10,2) NOT NULL,
    `quantity` INT NOT NULL,
    `subtotal` DECIMAL(10,2) NOT NULL,
    `experience_option_id` BIGINT,
    `order_id` BIGINT NOT NULL,
    `product_id` BIGINT NOT NULL,
    CONSTRAINT `fk_order_it_experien_9279abb9` FOREIGN KEY (`experience_option_id`) REFERENCES `experience_options` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_order_it_orders_b892ad0e` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_order_it_products_aebdc7ef` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT,
    KEY `idx_order_items_order_id` (`order_id`, `id`)
) CHARACTER SET utf8mb4 COMMENT='订单创建时写入的商品与 Experience Option 历史快照。';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    # This rollback deletes all Order data; execute it only after explicit approval
    # and a verified backup. The child table must be dropped before its parent.
    return """
        DROP TABLE IF EXISTS `order_items`;
        DROP TABLE IF EXISTS `orders`;"""


MODELS_STATE = (
    "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"
)
