"""外部支付边界；当前仅提供明确失败的禁用实现。"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.core.exceptions import ServiceUnavailableException


@dataclass(frozen=True, slots=True)
class PaymentInvocation:
    """未来由服务端签名后交给小程序收银台的最小参数。"""

    time_stamp: str
    nonce_str: str
    package: str
    sign_type: str
    pay_sign: str


class ExternalPaymentProvider(Protocol):
    """微信等外部资金渠道必须实现的窄接口。"""

    async def create_recharge(
        self,
        *,
        payment_no: str,
        amount: Decimal,
        user_id: int,
    ) -> PaymentInvocation: ...

    async def create_order_payment(
        self,
        *,
        payment_no: str,
        amount: Decimal,
        order_id: int,
        user_id: int,
    ) -> PaymentInvocation: ...

    async def create_refund(
        self,
        *,
        refund_no: str,
        payment_no: str,
        amount: Decimal,
    ) -> None: ...


class DisabledPaymentProvider:
    """在商户号、AppID 关联和 HTTPS 回调未就绪时 fail closed。"""

    @staticmethod
    def _unavailable() -> ServiceUnavailableException:
        return ServiceUnavailableException(
            message="WeChat payment is not available yet"
        )

    async def create_recharge(
        self,
        *,
        payment_no: str,
        amount: Decimal,
        user_id: int,
    ) -> PaymentInvocation:
        raise self._unavailable()

    async def create_order_payment(
        self,
        *,
        payment_no: str,
        amount: Decimal,
        order_id: int,
        user_id: int,
    ) -> PaymentInvocation:
        raise self._unavailable()

    async def create_refund(
        self,
        *,
        refund_no: str,
        payment_no: str,
        amount: Decimal,
    ) -> None:
        raise self._unavailable()
