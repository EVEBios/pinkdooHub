"""外部身份数据访问。"""

from tortoise.backends.base.client import BaseDBAsyncClient

from app.models.external_identity import ExternalIdentity


class ExternalIdentityRepository:
    """只封装外部身份查询和原子 CRUD。"""

    async def get_by_subject(
        self,
        *,
        provider: str,
        app_id: str,
        subject_id: str,
        using_db: BaseDBAsyncClient | None = None,
    ) -> ExternalIdentity | None:
        query = ExternalIdentity.filter(
            provider=provider,
            app_id=app_id,
            subject_id=subject_id,
        ).select_related("user")
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_by_union(
        self,
        *,
        provider: str,
        union_id: str,
        using_db: BaseDBAsyncClient | None = None,
    ) -> ExternalIdentity | None:
        query = ExternalIdentity.filter(
            provider=provider,
            union_id=union_id,
        ).select_related("user")
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_for_user_provider(
        self,
        *,
        user_id: int,
        provider: str,
        app_id: str,
        using_db: BaseDBAsyncClient | None = None,
    ) -> ExternalIdentity | None:
        query = ExternalIdentity.filter(
            user_id=user_id,
            provider=provider,
            app_id=app_id,
        )
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def list_for_user(self, user_id: int) -> list[ExternalIdentity]:
        return await ExternalIdentity.filter(user_id=user_id).order_by("provider", "id")

    async def create(
        self,
        *,
        provider: str,
        app_id: str,
        subject_id: str,
        union_id: str | None,
        user_id: int,
        using_db: BaseDBAsyncClient,
    ) -> ExternalIdentity:
        return await ExternalIdentity.create(
            provider=provider,
            app_id=app_id,
            subject_id=subject_id,
            union_id=union_id,
            user_id=user_id,
            using_db=using_db,
        )

    async def delete(
        self,
        identity: ExternalIdentity,
        *,
        using_db: BaseDBAsyncClient,
    ) -> None:
        await identity.delete(using_db=using_db)

    async def delete_all_for_user(
        self,
        user_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> int:
        return await ExternalIdentity.filter(user_id=user_id).using_db(using_db).delete()
