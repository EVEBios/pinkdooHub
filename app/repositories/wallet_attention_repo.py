"""逐笔余额调整结果；事件键引用不可变流水，读取时复验钱包归属。"""

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.queryset import QuerySet

from app.common.enums.attention import AttentionEventType
from app.common.enums.wallet import WalletTransactionType
from app.models.attention import AttentionEvent
from app.models.wallet import WalletTransaction


class WalletAttentionRepository:
    def query(self, user_id: int, *, using_db: BaseDBAsyncClient) -> QuerySet[AttentionEvent]:
        return AttentionEvent.filter(
            user_id=user_id, event_type=AttentionEventType.WALLET_ADJUSTED,
            order_id=None, session_id=None, reservation_id=None,
        ).using_db(using_db)

    async def count_unread(self, user_id: int, *, using_db: BaseDBAsyncClient) -> int:
        return await self.query(user_id, using_db=using_db).filter(read_at=None).count()

    async def list_events(self, user_id: int, *, unread: bool, page: int,
                          page_size: int, using_db: BaseDBAsyncClient) -> tuple[list[AttentionEvent], int]:
        query = self.query(user_id, using_db=using_db)
        if unread:
            query = query.filter(read_at=None)
        total = await query.count()
        events = await query.order_by("-occurred_at", "-id").offset((page - 1) * page_size).limit(page_size)
        return list(events), total

    async def get_result(self, event_id: int, user_id: int, *, using_db: BaseDBAsyncClient
                         ) -> tuple[AttentionEvent, WalletTransaction] | None:
        event = await self.query(user_id, using_db=using_db).filter(id=event_id).first()
        if event is None:
            return None
        parts = event.event_key.split(":")
        if len(parts) != 3 or parts[0] != "wallet_transaction" or parts[2] != "wallet_adjusted" or not parts[1].isdigit():
            return None
        transaction = await WalletTransaction.filter(
            id=int(parts[1]), wallet_account__user_id=user_id,
            transaction_type=WalletTransactionType.ADMIN_ADJUSTMENT,
        ).using_db(using_db).first()
        return (event, transaction) if transaction is not None else None
