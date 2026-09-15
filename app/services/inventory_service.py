"""Inventory Service —— 管理员库存调整业务编排。"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError, OperationalError
from tortoise.transactions import in_transaction

from app.common.constants.inventory import (
    INVENTORY_ADMIN_COLOR_IDEMPOTENCY_PREFIX,
    INVENTORY_ADMIN_IDEMPOTENCY_PREFIX,
    INVENTORY_AUDIT_ACTION_ADJUST,
    INVENTORY_AUDIT_TARGET_TYPE,
    INVENTORY_RETRYABLE_MYSQL_ERROR_CODES,
    INVENTORY_STOCK_MAX,
    INVENTORY_STOCK_MIN,
    INVENTORY_TRANSACTION_MAX_ATTEMPTS,
)
from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.common.enums.product import KitKind, ProductType
from app.common.exceptions import (
    InventoryBalanceExceeded,
    InventoryKitKindMismatch,
    InventoryTransactionConflict,
    ProductIsDeleted,
    ProductKitNotFound,
    ProductKitColorNotFound,
    ProductNotFound,
    ProductTypeMismatch,
)
from app.common.pagination import Page
from app.models.inventory_transaction import InventoryTransaction
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.repositories.inventory_repo import (
    InventoryRepository,
    InventoryTransactionCreateData,
)
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.utils.database import get_database_error_code

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InventoryAdjustmentResult:
    """库存调整领域结果；供 API 区分首次创建与幂等重放。"""

    product_id: int
    stock: int
    transaction: InventoryTransaction
    is_replay: bool


@dataclass(frozen=True, slots=True)
class InventoryColorAdjustmentResult:
    """可选颜色库存调整结果；余额单位固定为 10g。"""

    product_id: int
    kit_color_id: int
    stock_units: int
    transaction: InventoryTransaction
    is_replay: bool


class InventoryService:
    """Inventory 查询编排与管理写用例的业务规则所有者。"""

    def __init__(
        self,
        inventory_repository: InventoryRepository,
        product_repository: ProductRepository,
        audit_log_service: AuditLogService,
    ) -> None:
        self.inventory_repository = inventory_repository
        self.product_repository = product_repository
        self.audit_log_service = audit_log_service

    async def adjust_stock(
        self,
        product_id: int,
        *,
        change: int,
        reason: str,
        operator_id: int,
        ip_address: str,
        idempotency_key: str,
    ) -> InventoryAdjustmentResult:
        """原子调整 Kit 库存，并安全处理幂等重放与 MySQL 瞬态冲突。"""

        internal_key = f"{INVENTORY_ADMIN_IDEMPOTENCY_PREFIX}{idempotency_key}"
        for attempt in range(1, INVENTORY_TRANSACTION_MAX_ATTEMPTS + 1):
            try:
                result = await self._adjust_once(
                    product_id=product_id,
                    change=change,
                    reason=reason,
                    operator_id=operator_id,
                    ip_address=ip_address,
                    internal_key=internal_key,
                )
            except IntegrityError:
                replay = await self._resolve_committed_idempotency(
                    internal_key=internal_key,
                    product_id=product_id,
                    change=change,
                    reason=reason,
                    operator_id=operator_id,
                )
                if replay is None:
                    raise
                result = replay
            except OperationalError as exc:
                error_code = get_database_error_code(exc)
                if (
                    error_code not in INVENTORY_RETRYABLE_MYSQL_ERROR_CODES
                    or attempt >= INVENTORY_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
                logger.warning(
                    "Retrying inventory adjustment after MySQL transient error: "
                    "operator_id=%d product_id=%d error_code=%d attempt=%d",
                    operator_id,
                    product_id,
                    error_code,
                    attempt,
                )
                continue

            logger.info(
                "Inventory adjusted: operator_id=%d product_id=%d replay=%s",
                operator_id,
                product_id,
                result.is_replay,
            )
            return result

        raise RuntimeError("Inventory adjustment retry loop exhausted")

    async def adjust_color_stock(
        self,
        product_id: int,
        kit_color_id: int,
        *,
        change: int,
        reason: str,
        operator_id: int,
        ip_address: str,
        idempotency_key: str,
    ) -> InventoryColorAdjustmentResult:
        """原子调整一个商品颜色的 10g 单位库存。"""

        internal_key = (
            f"{INVENTORY_ADMIN_COLOR_IDEMPOTENCY_PREFIX}{idempotency_key}"
        )
        for attempt in range(1, INVENTORY_TRANSACTION_MAX_ATTEMPTS + 1):
            try:
                result = await self._adjust_color_once(
                    product_id=product_id,
                    kit_color_id=kit_color_id,
                    change=change,
                    reason=reason,
                    operator_id=operator_id,
                    ip_address=ip_address,
                    internal_key=internal_key,
                )
            except IntegrityError:
                replay = await self._resolve_committed_color_idempotency(
                    internal_key=internal_key,
                    product_id=product_id,
                    kit_color_id=kit_color_id,
                    change=change,
                    reason=reason,
                    operator_id=operator_id,
                )
                if replay is None:
                    raise
                result = replay
            except OperationalError as exc:
                error_code = get_database_error_code(exc)
                if (
                    error_code not in INVENTORY_RETRYABLE_MYSQL_ERROR_CODES
                    or attempt >= INVENTORY_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
                logger.warning(
                    "Retrying color inventory adjustment after MySQL transient "
                    "error: operator_id=%d product_id=%d kit_color_id=%d "
                    "error_code=%d attempt=%d",
                    operator_id,
                    product_id,
                    kit_color_id,
                    error_code,
                    attempt,
                )
                continue

            logger.info(
                "Color inventory adjusted: operator_id=%d product_id=%d "
                "kit_color_id=%d replay=%s",
                operator_id,
                product_id,
                kit_color_id,
                result.is_replay,
            )
            return result

        raise RuntimeError("Color inventory adjustment retry loop exhausted")

    async def list_product_transactions(
        self,
        product_id: int,
        *,
        page: int,
        page_size: int,
        transaction_type: InventoryTransactionType | None = None,
        source_type: InventorySourceType | None = None,
        source_id: int | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> Page[InventoryTransaction]:
        """校验指定 Kit Product 后分页查询其库存流水。"""

        product = await self._get_product(product_id)
        self._validate_kit_product_identity(product)
        kits = await self.product_repository.get_kits_by_product_ids(
            {product_id}
        )
        if not kits:
            raise ProductKitNotFound()
        self._validate_kit_kind(kits[0], expected=KitKind.FIXED)
        return await self.inventory_repository.list_transactions(
            page=page,
            page_size=page_size,
            product_id=product_id,
            transaction_type=transaction_type,
            source_type=source_type,
            source_id=source_id,
            created_from=created_from,
            created_to=created_to,
        )

    async def list_product_color_transactions(
        self,
        product_id: int,
        kit_color_id: int,
        *,
        page: int,
        page_size: int,
        transaction_type: InventoryTransactionType | None = None,
        source_type: InventorySourceType | None = None,
        source_id: int | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> Page[InventoryTransaction]:
        """校验颜色归属后分页查询一个 10g 单位余额的流水。"""

        product = await self._get_product(product_id)
        self._validate_kit_product_identity(product)
        kits = await self.product_repository.get_kits_by_product_ids(
            {product_id}
        )
        if not kits:
            raise ProductKitNotFound()
        self._validate_kit_kind(kits[0], expected=KitKind.COLOR_SELECTABLE)
        kit_color = await self.product_repository.get_product_kit_color_by_id(
            kit_color_id
        )
        if kit_color is None or kit_color.product_id != product_id:
            raise ProductKitColorNotFound()
        return await self.inventory_repository.list_transactions(
            page=page,
            page_size=page_size,
            product_id=product_id,
            kit_color_id=kit_color_id,
            transaction_type=transaction_type,
            source_type=source_type,
            source_id=source_id,
            created_from=created_from,
            created_to=created_to,
        )

    async def list_transactions(
        self,
        *,
        page: int,
        page_size: int,
        product_id: int | None = None,
        kit_color_id: int | None = None,
        transaction_type: InventoryTransactionType | None = None,
        source_type: InventorySourceType | None = None,
        source_id: int | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> Page[InventoryTransaction]:
        """分页查询全局库存流水，不把筛选 ID 解释为资源读取。"""

        return await self.inventory_repository.list_transactions(
            page=page,
            page_size=page_size,
            product_id=product_id,
            kit_color_id=kit_color_id,
            transaction_type=transaction_type,
            source_type=source_type,
            source_id=source_id,
            created_from=created_from,
            created_to=created_to,
        )

    async def _adjust_once(
        self,
        *,
        product_id: int,
        change: int,
        reason: str,
        operator_id: int,
        ip_address: str,
        internal_key: str,
    ) -> InventoryAdjustmentResult:
        """在一条全新事务中执行一次完整调整尝试。"""

        async with in_transaction() as connection:
            kit = await self.inventory_repository.get_kit_for_update(
                product_id,
                using_db=connection,
            )
            product = await self._get_product(
                product_id,
                using_db=connection,
            )
            kit = self._validate_kit_product(
                product,
                kit,
                expected_kind=KitKind.FIXED,
            )

            existing = (
                await self.inventory_repository.get_transaction_by_idempotency_key(
                    internal_key,
                    using_db=connection,
                )
            )
            if existing is not None:
                return await self._result_from_existing(
                    existing,
                    product_id=product_id,
                    change=change,
                    reason=reason,
                    operator_id=operator_id,
                    using_db=connection,
                )

            before_quantity = kit.stock
            if before_quantity is None:
                raise InventoryTransactionConflict()
            after_quantity = before_quantity + change
            if not INVENTORY_STOCK_MIN <= after_quantity <= INVENTORY_STOCK_MAX:
                raise InventoryBalanceExceeded(
                    product_id=product_id,
                    before_quantity=before_quantity,
                    change_quantity=change,
                )

            await self.inventory_repository.update_stock(
                kit,
                stock=after_quantity,
                using_db=connection,
            )
            transaction = await self.inventory_repository.create_transaction(
                data=InventoryTransactionCreateData(
                    product_id=product_id,
                    transaction_type=InventoryTransactionType.ADMIN_ADJUSTMENT,
                    change_quantity=change,
                    before_quantity=before_quantity,
                    after_quantity=after_quantity,
                    source_type=InventorySourceType.ADMIN,
                    source_id=None,
                    operator_id=operator_id,
                    reason=reason,
                    idempotency_key=internal_key,
                ),
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action=INVENTORY_AUDIT_ACTION_ADJUST,
                target_type=INVENTORY_AUDIT_TARGET_TYPE,
                target_id=product_id,
                ip_address=ip_address,
                description=_audit_description(
                    transaction_id=transaction.id,
                    before_quantity=before_quantity,
                    change_quantity=change,
                    after_quantity=after_quantity,
                ),
                using_db=connection,
            )
            detail = await self.inventory_repository.get_transaction_detail(
                transaction.id,
                using_db=connection,
            )
            if detail is None:
                raise RuntimeError("Created inventory transaction not found")

            return InventoryAdjustmentResult(
                product_id=product_id,
                stock=after_quantity,
                transaction=detail,
                is_replay=False,
            )

    async def _adjust_color_once(
        self,
        *,
        product_id: int,
        kit_color_id: int,
        change: int,
        reason: str,
        operator_id: int,
        ip_address: str,
        internal_key: str,
    ) -> InventoryColorAdjustmentResult:
        """在一条全新事务中执行一次商品颜色库存调整。"""

        async with in_transaction() as connection:
            kit_color = await self.inventory_repository.get_kit_color_for_update(
                kit_color_id,
                using_db=connection,
            )
            product = await self._get_product(
                product_id,
                using_db=connection,
            )
            kits = await self.product_repository.get_kits_by_product_ids(
                {product_id},
                using_db=connection,
            )
            self._validate_kit_product(
                product,
                kits[0] if kits else None,
                expected_kind=KitKind.COLOR_SELECTABLE,
            )
            if kit_color is None or kit_color.product_id != product_id:
                raise ProductKitColorNotFound()

            existing = (
                await self.inventory_repository.get_transaction_by_idempotency_key(
                    internal_key,
                    using_db=connection,
                )
            )
            if existing is not None:
                return await self._color_result_from_existing(
                    existing,
                    product_id=product_id,
                    kit_color_id=kit_color_id,
                    change=change,
                    reason=reason,
                    operator_id=operator_id,
                    using_db=connection,
                )

            before_quantity = kit_color.stock_units
            after_quantity = before_quantity + change
            if not INVENTORY_STOCK_MIN <= after_quantity <= INVENTORY_STOCK_MAX:
                raise InventoryBalanceExceeded(
                    product_id=product_id,
                    kit_color_id=kit_color_id,
                    before_quantity=before_quantity,
                    change_quantity=change,
                )

            await self.inventory_repository.update_color_stock(
                kit_color,
                stock_units=after_quantity,
                using_db=connection,
            )
            transaction = await self.inventory_repository.create_transaction(
                data=InventoryTransactionCreateData(
                    product_id=product_id,
                    kit_color_id=kit_color_id,
                    transaction_type=InventoryTransactionType.ADMIN_ADJUSTMENT,
                    change_quantity=change,
                    before_quantity=before_quantity,
                    after_quantity=after_quantity,
                    source_type=InventorySourceType.ADMIN,
                    source_id=None,
                    operator_id=operator_id,
                    reason=reason,
                    idempotency_key=internal_key,
                ),
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action=INVENTORY_AUDIT_ACTION_ADJUST,
                target_type=INVENTORY_AUDIT_TARGET_TYPE,
                target_id=product_id,
                ip_address=ip_address,
                description=_audit_description(
                    transaction_id=transaction.id,
                    before_quantity=before_quantity,
                    change_quantity=change,
                    after_quantity=after_quantity,
                    kit_color_id=kit_color_id,
                ),
                using_db=connection,
            )
            detail = await self.inventory_repository.get_transaction_detail(
                transaction.id,
                using_db=connection,
            )
            if detail is None:
                raise RuntimeError("Created color inventory transaction not found")

            return InventoryColorAdjustmentResult(
                product_id=product_id,
                kit_color_id=kit_color_id,
                stock_units=after_quantity,
                transaction=detail,
                is_replay=False,
            )

    async def _get_product(
        self,
        product_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Product:
        products = await self.product_repository.get_products_by_ids(
            {product_id},
            using_db=using_db,
        )
        if not products:
            raise ProductNotFound()
        return products[0]

    @staticmethod
    def _validate_kit_product(
        product: Product,
        kit: ProductKit | None,
        *,
        expected_kind: KitKind,
    ) -> ProductKit:
        InventoryService._validate_kit_product_identity(product)
        if kit is None:
            raise ProductKitNotFound()
        InventoryService._validate_kit_kind(kit, expected=expected_kind)
        return kit

    @staticmethod
    def _validate_kit_kind(kit: ProductKit, *, expected: KitKind) -> None:
        if kit.kit_kind is not expected:
            raise InventoryKitKindMismatch(
                expected=expected,
                actual=kit.kit_kind,
            )

    @staticmethod
    def _validate_kit_product_identity(product: Product) -> None:
        """按稳定优先级校验 Product 可作为 Kit 聚合根。"""

        if product.is_deleted:
            raise ProductIsDeleted()
        if product.product_type is not ProductType.KIT:
            raise ProductTypeMismatch(
                expected=ProductType.KIT,
                actual=product.product_type,
            )

    async def _result_from_existing(
        self,
        transaction: InventoryTransaction,
        *,
        product_id: int,
        change: int,
        reason: str,
        operator_id: int,
        using_db: BaseDBAsyncClient | None,
    ) -> InventoryAdjustmentResult:
        if not _matches_adjustment(
            transaction,
            product_id=product_id,
            change=change,
            reason=reason,
            operator_id=operator_id,
        ):
            raise InventoryTransactionConflict()
        detail = await self.inventory_repository.get_transaction_detail(
            transaction.id,
            using_db=using_db,
        )
        if detail is None:
            raise RuntimeError("Idempotent inventory transaction not found")
        return InventoryAdjustmentResult(
            product_id=detail.product_id,
            stock=detail.after_quantity,
            transaction=detail,
            is_replay=True,
        )

    async def _color_result_from_existing(
        self,
        transaction: InventoryTransaction,
        *,
        product_id: int,
        kit_color_id: int,
        change: int,
        reason: str,
        operator_id: int,
        using_db: BaseDBAsyncClient | None,
    ) -> InventoryColorAdjustmentResult:
        if not _matches_adjustment(
            transaction,
            product_id=product_id,
            kit_color_id=kit_color_id,
            change=change,
            reason=reason,
            operator_id=operator_id,
        ):
            raise InventoryTransactionConflict()
        detail = await self.inventory_repository.get_transaction_detail(
            transaction.id,
            using_db=using_db,
        )
        if detail is None:
            raise RuntimeError("Idempotent color inventory transaction not found")
        return InventoryColorAdjustmentResult(
            product_id=detail.product_id,
            kit_color_id=kit_color_id,
            stock_units=detail.after_quantity,
            transaction=detail,
            is_replay=True,
        )

    async def _resolve_committed_idempotency(
        self,
        *,
        internal_key: str,
        product_id: int,
        change: int,
        reason: str,
        operator_id: int,
    ) -> InventoryAdjustmentResult | None:
        transaction = (
            await self.inventory_repository.get_transaction_by_idempotency_key(
                internal_key
            )
        )
        if transaction is None:
            return None
        return await self._result_from_existing(
            transaction,
            product_id=product_id,
            change=change,
            reason=reason,
            operator_id=operator_id,
            using_db=None,
        )

    async def _resolve_committed_color_idempotency(
        self,
        *,
        internal_key: str,
        product_id: int,
        kit_color_id: int,
        change: int,
        reason: str,
        operator_id: int,
    ) -> InventoryColorAdjustmentResult | None:
        transaction = (
            await self.inventory_repository.get_transaction_by_idempotency_key(
                internal_key
            )
        )
        if transaction is None:
            return None
        return await self._color_result_from_existing(
            transaction,
            product_id=product_id,
            kit_color_id=kit_color_id,
            change=change,
            reason=reason,
            operator_id=operator_id,
            using_db=None,
        )


def _matches_adjustment(
    transaction: InventoryTransaction,
    *,
    product_id: int,
    kit_color_id: int | None = None,
    change: int,
    reason: str,
    operator_id: int,
) -> bool:
    """确认数据库幂等身份绑定到完全相同的规范化请求。"""

    return (
        transaction.transaction_type is InventoryTransactionType.ADMIN_ADJUSTMENT
        and transaction.source_type is InventorySourceType.ADMIN
        and transaction.source_id is None
        and transaction.product_id == product_id
        and transaction.kit_color_id == kit_color_id
        and transaction.change_quantity == change
        and transaction.reason == reason
        and transaction.operator_id == operator_id
    )


def _audit_description(
    *,
    transaction_id: int,
    before_quantity: int,
    change_quantity: int,
    after_quantity: int,
    kit_color_id: int | None = None,
) -> str:
    """生成不含原因和幂等键的稳定紧凑审计快照。"""

    payload = {
        "transaction_id": transaction_id,
        "before_quantity": before_quantity,
        "change_quantity": change_quantity,
        "after_quantity": after_quantity,
    }
    if kit_color_id is not None:
        payload["kit_color_id"] = kit_color_id
    return json.dumps(
        payload,
        separators=(",", ":"),
    )
