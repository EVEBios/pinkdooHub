from tortoise import BaseDBAsyncClient

# MySQL DDL implicitly commits; this migration cannot promise atomic rollback.
RUN_IN_TRANSACTION = False


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE `wallet_accounts` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `balance` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `status` VARCHAR(32) NOT NULL COMMENT 'ACTIVE: active\nCLOSED: closed' DEFAULT 'active',
    `user_id` BIGINT NOT NULL UNIQUE,
    CONSTRAINT `fk_wallet_a_users_77c8a4f3` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT
) CHARACTER SET utf8mb4 COMMENT='一个 User 唯一拥有的权威钱包余额。';
        CREATE TABLE `recharge_orders` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `recharge_no` VARCHAR(28) NOT NULL UNIQUE,
    `amount` DECIMAL(10,2) NOT NULL,
    `status` VARCHAR(32) NOT NULL COMMENT 'PENDING: pending\nPAID: paid\nFAILED: failed\nCLOSED: closed' DEFAULT 'pending',
    `idempotency_key` VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `succeeded_at` DATETIME(6),
    `user_id` BIGINT NOT NULL,
    `wallet_account_id` BIGINT NOT NULL,
    CONSTRAINT `fk_recharge_users_4ed5b2ae` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_recharge_wallet_a_55c7df89` FOREIGN KEY (`wallet_account_id`) REFERENCES `wallet_accounts` (`id`) ON DELETE RESTRICT,
    UNIQUE KEY `uidx_recharge_order_idempotency` (`idempotency_key`),
    KEY `idx_recharge_order_user_created_id` (`user_id`, `created_at`, `id`),
    KEY `idx_recharge_order_status_created_id` (`status`, `created_at`, `id`)
) CHARACTER SET utf8mb4 COMMENT='用户为自己钱包发起的单笔充值业务单。';
        CREATE TABLE `payments` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `payment_no` VARCHAR(28) NOT NULL UNIQUE,
    `purpose` VARCHAR(32) NOT NULL COMMENT 'ORDER: order\nRECHARGE: recharge',
    `method` VARCHAR(32) NOT NULL COMMENT 'WALLET: wallet\nWECHAT: wechat\nMANUAL: manual',
    `amount` DECIMAL(10,2) NOT NULL,
    `status` VARCHAR(32) NOT NULL COMMENT 'PENDING: pending\nSUCCEEDED: succeeded\nFAILED: failed\nCLOSED: closed' DEFAULT 'pending',
    `idempotency_key` VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `provider_transaction_id` VARCHAR(128),
    `succeeded_at` DATETIME(6),
    `order_id` BIGINT,
    `recharge_order_id` BIGINT,
    `user_id` BIGINT NOT NULL,
    CONSTRAINT `fk_payments_orders_82d56ff1` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_payments_recharge_89f86c1b` FOREIGN KEY (`recharge_order_id`) REFERENCES `recharge_orders` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_payments_users_5514215d` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
    UNIQUE KEY `uidx_payment_idempotency` (`idempotency_key`),
    UNIQUE KEY `uidx_payment_provider_transaction` (`provider_transaction_id`),
    KEY `idx_payment_user_created_id` (`user_id`, `created_at`, `id`),
    KEY `idx_payment_order_created_id` (`order_id`, `created_at`, `id`),
    KEY `idx_payment_recharge_created_id` (`recharge_order_id`, `created_at`, `id`),
    KEY `idx_payment_status_created_id` (`status`, `created_at`, `id`)
) CHARACTER SET utf8mb4 COMMENT='订单或充值业务的一次支付记录。';
        CREATE TABLE `payment_settlements` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `amount` DECIMAL(10,2) NOT NULL,
    `payment_id` BIGINT NOT NULL UNIQUE,
    `order_id` BIGINT NOT NULL UNIQUE,
    CONSTRAINT `fk_payment__payments_699ef5f6` FOREIGN KEY (`payment_id`) REFERENCES `payments` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_payment__orders_77d69fda` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`) ON DELETE RESTRICT
) CHARACTER SET utf8mb4 COMMENT='成功 Payment 与 Order 的唯一结算事实。';
        CREATE TABLE `refunds` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `refund_no` VARCHAR(28) NOT NULL UNIQUE,
    `amount` DECIMAL(10,2) NOT NULL,
    `status` VARCHAR(32) NOT NULL COMMENT 'PENDING: pending\nSUCCEEDED: succeeded\nFAILED: failed' DEFAULT 'pending',
    `inventory_restored` BOOL NOT NULL DEFAULT 0,
    `reason` VARCHAR(256) NOT NULL,
    `idempotency_key` VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `provider_refund_id` VARCHAR(128),
    `succeeded_at` DATETIME(6),
    `operator_id` BIGINT NOT NULL,
    `order_id` BIGINT NOT NULL UNIQUE,
    `settlement_id` BIGINT NOT NULL UNIQUE,
    CONSTRAINT `fk_refunds_users_4b9d10bc` FOREIGN KEY (`operator_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_refunds_orders_48a3358d` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_refunds_payment__c6d9454a` FOREIGN KEY (`settlement_id`) REFERENCES `payment_settlements` (`id`) ON DELETE RESTRICT,
    UNIQUE KEY `uidx_refund_idempotency` (`idempotency_key`),
    UNIQUE KEY `uidx_refund_provider_reference` (`provider_refund_id`),
    KEY `idx_refund_order_created_id` (`order_id`, `created_at`, `id`),
    KEY `idx_refund_status_created_id` (`status`, `created_at`, `id`)
) CHARACTER SET utf8mb4 COMMENT='一个成功结算最多对应一次全额退款。';
        CREATE TABLE `wallet_transactions` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `transaction_type` VARCHAR(32) NOT NULL COMMENT 'RECHARGE: recharge\nORDER_PAYMENT: order_payment\nADMIN_ADJUSTMENT: admin_adjustment\nREFUND: refund',
    `change_amount` DECIMAL(10,2) NOT NULL,
    `before_balance` DECIMAL(10,2) NOT NULL,
    `after_balance` DECIMAL(10,2) NOT NULL,
    `source_type` VARCHAR(32) NOT NULL COMMENT 'RECHARGE_ORDER: recharge_order\nORDER: order\nADMIN: admin\nREFUND: refund',
    `source_id` BIGINT,
    `reason` VARCHAR(256) NOT NULL,
    `idempotency_key` VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `operator_id` BIGINT,
    `wallet_account_id` BIGINT NOT NULL,
    CONSTRAINT `fk_wallet_t_users_c609e24a` FOREIGN KEY (`operator_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_wallet_t_wallet_a_2784aeb9` FOREIGN KEY (`wallet_account_id`) REFERENCES `wallet_accounts` (`id`) ON DELETE RESTRICT,
    UNIQUE KEY `uidx_wallet_transaction_idempotency` (`idempotency_key`),
    KEY `idx_wallet_transaction_wallet_created_id` (`wallet_account_id`, `created_at`, `id`),
    KEY `idx_wallet_transaction_source_created_id` (`source_type`, `source_id`, `created_at`, `id`),
    KEY `idx_wallet_transaction_type_created_id` (`transaction_type`, `created_at`, `id`),
    KEY `idx_wallet_transaction_created_id` (`created_at`, `id`)
) CHARACTER SET utf8mb4 COMMENT='记录每一次已提交余额变化；Repository 不提供修改或删除入口。';
        ALTER TABLE `inventory_transactions` MODIFY COLUMN `transaction_type` VARCHAR(40) NOT NULL COMMENT 'OPENING_BALANCE: opening_balance\nADMIN_ADJUSTMENT: admin_adjustment\nORDER_DEDUCTION: order_deduction\nORDER_CANCELLATION_RESTORE: order_cancellation_restore\nORDER_REFUND_RESTORE: order_refund_restore';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    # This removes all Wallet/Payment/Refund facts. Once runtime writes exist,
    # prefer a reviewed forward fix and require a verified backup for downgrade.
    return """
        ALTER TABLE `inventory_transactions` MODIFY COLUMN `transaction_type` VARCHAR(40) NOT NULL COMMENT 'OPENING_BALANCE: opening_balance\nADMIN_ADJUSTMENT: admin_adjustment\nORDER_DEDUCTION: order_deduction\nORDER_CANCELLATION_RESTORE: order_cancellation_restore';
        DROP TABLE IF EXISTS `wallet_transactions`;
        DROP TABLE IF EXISTS `refunds`;
        DROP TABLE IF EXISTS `payment_settlements`;
        DROP TABLE IF EXISTS `payments`;
        DROP TABLE IF EXISTS `recharge_orders`;
        DROP TABLE IF EXISTS `wallet_accounts`;"""


MODELS_STATE = (
    "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"
)
