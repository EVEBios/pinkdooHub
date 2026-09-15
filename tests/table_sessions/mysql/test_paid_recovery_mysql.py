"""在真实已迁移 MySQL 上核验已付款失败及并发 Token 比较交换。"""
import asyncio

from app.tasks import gatea_m9_paid_acceptance_verify as paid
from app.tasks import gatea_m9_qr_rotate as qr
from tests.release.test_gatea_m9_failed_acceptance_verify import _seed_paid_failure


async def test_paid_failure_verifier_matches_real_mysql_facts():
    _, data = await _seed_paid_failure()
    assert (await paid.verify_paid_acceptance(**data))['passed'] is True


async def test_concurrent_qr_rotation_commits_one_value_and_rejects_stale_compare():
    await _seed_paid_failure()
    results = await asyncio.gather(*(
        qr.rotate({'mode': 'apply', 'old_sha256': qr.digest('A' * 32), 'new_token': value * 32})
        for value in ('B', 'C')
    ), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    current = await qr.rotate({'mode': 'inspect'})
    assert current == next(result for result in results if isinstance(result, dict))
    assert await qr.rotate({'mode': 'verify', 'old_sha256': qr.digest('A' * 32),
                            'new_sha256': current['current_sha256']}) == current
