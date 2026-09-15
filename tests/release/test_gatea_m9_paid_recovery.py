"""已支付恢复：真实事务及宿主中断/恢复/证据绑定边界。"""
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from app.models.table_session import StoreTable
from app.tasks import gatea_m9_qr_rotate as qr
from scripts.release import gatea_candidate as candidate
from scripts.release import gatea_m9_paid_recovery as recovery
from tortoise import Tortoise
from tests.release.test_gatea_m9_failed_acceptance_verify import _seed_paid_failure


async def _read_footprint():
    return {model._meta.db_table: list(await model.all().order_by("id").values())
            for model in Tortoise.apps["models"].values()}


async def test_real_qr_rotation_changes_only_t01_token_and_old_code_stops_resolving(client):
    await _seed_paid_failure()
    before = await _read_footprint()
    original = await StoreTable.get(table_no='T01')
    token = 'B' * 32
    planned = {'mode': 'apply', 'old_sha256': qr.digest(original.qr_token), 'new_token': token}
    result = await qr.rotate(planned)
    assert result['current_sha256'] == qr.digest(token)
    assert original.qr_token not in json.dumps(result) and token not in json.dumps(result)
    assert not await StoreTable.filter(qr_token=original.qr_token).exists()
    assert (await StoreTable.get(qr_token=token)).table_no == 'T01'
    assert (await client.get('/api/v1/table-codes/' + original.qr_token)).status_code == 404
    assert (await client.get('/api/v1/table-codes/' + token)).status_code == 200
    after = await _read_footprint()
    # Snapshot helper includes every registered ORM table.
    for rows in (before, after):
        for row in rows['store_tables']:
            if row['table_no'] == 'T01':
                row['qr_token'] = '<rotation>'
    assert after == before
    assert await qr.rotate(planned) == result


async def test_real_qr_rotation_rejects_wrong_compare_digest_without_writes():
    await _seed_paid_failure()
    before = await _read_footprint()
    with pytest.raises(ValueError, match='drift'):
        await qr.rotate({'mode': 'apply', 'old_sha256': '0' * 64, 'new_token': 'C' * 32})
    assert await _read_footprint() == before


@pytest.mark.parametrize('interruption', ['none', 'before_commit', 'after_commit', 'restore', 'publication', 'cleanup'])
def test_host_rotation_recovers_exact_checkpoint_and_restores_runtime(monkeypatch, tmp_path, interruption):
    monkeypatch.setattr(candidate, 'ROOT_UID', __import__('os').getuid())
    monkeypatch.setattr(candidate, 'ROOT_GID', __import__('os').getgid())
    monkeypatch.setattr(candidate.os, 'fchown', lambda *args: None)
    monkeypatch.setattr(candidate.os, 'chown', lambda *args: None)
    target, predecessor = 'f' * 40, 'e' * 40
    records = tmp_path / 'records'
    records.mkdir()
    deployment = {'candidate_sha': target, 'source_candidate_sha': predecessor, 'image_id': 'sha256:' + 'a' * 64,
                  'acceptance_retirement_record_sha256': 'b' * 64, 'backup_id': '20260915t111822z'}
    context = {'context': {'retirement': {'acceptance_archive_sha256': 'c' * 64}}, 'failed': {}}
    monkeypatch.setattr(recovery.gatea, 'REPOSITORY_ROOT', tmp_path / target)
    for name in ('_require_execution_release', '_load_stage', '_reject_unresolved_transition_journals', '_require_root_file'):
        monkeypatch.setattr(candidate, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(recovery, 'paid_context', lambda **kwargs: context)
    monkeypatch.setattr(recovery.gatea, '_validated_inputs', lambda **kwargs: {'GATEA_APP_IMAGE': target})
    monkeypatch.setattr(recovery.gatea, '_candidate_sha', lambda values: target)
    monkeypatch.setattr(recovery.gatea, 'validate_app_image', lambda values: deployment['image_id'])
    monkeypatch.setattr(recovery.gatea, '_require_upgrade_record', lambda **kwargs: deployment)
    monkeypatch.setattr(recovery.gatea, '_require_m9_upgrade_replay_record', lambda **kwargs: {})
    monkeypatch.setattr(recovery.gatea, '_run_compose', lambda **kwargs: None)
    monkeypatch.setattr(recovery.gatea, '_compose_ps', lambda **kwargs: [])
    monkeypatch.setattr(recovery.upgrade, '_ensure_not_running', lambda *args: None)
    monkeypatch.setattr(recovery.gatea, '_ensure_services_healthy', lambda *args: None)
    monkeypatch.setattr(candidate, '_failed_acceptance_business_verification', lambda **kwargs: {})
    live = {'current': qr.digest('A' * 32), 'commits': 0, 'restores': 0, 'failed': False}
    final_path = records / (target + recovery.RECORD_SUFFIX)
    pending_path = final_path.with_suffix('.json.pending')
    def fail_at(point):
        if interruption == point and not live['failed']:
            live['failed'] = True
            raise OSError('injected ' + point)
    def task(values, config, secret, payload):
        if payload['mode'] == 'apply':
            durable = json.loads(pending_path.read_text())
            assert durable['new_sha256'] == qr.digest(payload['new_token'])
            assert payload['new_token'] not in pending_path.read_text()
            fail_at('before_commit')
            live['current'] = qr.digest(payload['new_token'])
            live['commits'] += 1
            fail_at('after_commit')
        return {'current_sha256': live['current']}
    def restore(**kwargs):
        live['restores'] += 1
        fail_at('restore')
    monkeypatch.setattr(recovery, '_task', task)
    monkeypatch.setattr(recovery.gatea, 'app_up', restore)
    original_write = candidate._write_json_exclusive
    def write(path, payload, mode=0o644):
        if path == final_path:
            fail_at('publication')
        original_write(path, payload, mode)
    monkeypatch.setattr(candidate, '_write_json_exclusive', write)
    original_unlink = Path.unlink
    def unlink(path, *args, **kwargs):
        if path == pending_path and final_path.exists():
            fail_at('cleanup')
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', unlink)
    args = dict(confirm_target_sha=target, confirm_failed_acceptance_sha256='c' * 64,
                release_record_dir=records, _termination_controller=SimpleNamespace(begin_recovery=lambda: None))
    if interruption != 'none':
        with pytest.raises(OSError, match='injected'):
            recovery.recover.__wrapped__(**args)
        assert live['restores'] == 1
        assert pending_path.exists()
    result = recovery.recover.__wrapped__(**args)
    assert result['passed'] and result['runtime_restored'] and result['old_token_invalid']
    assert live['commits'] == 1
    assert not pending_path.exists()
    assert recovery.recover.__wrapped__(**args) == result
    assert live['commits'] == 1


@pytest.mark.parametrize('field', ['failed_acceptance_sha256', 'predecessor_candidate_sha', 'image_id', 'backup_id', 'old_sha256', 'new_sha256', 'runtime_restored'])
def test_rotation_record_rejects_rebinding(field):
    binding = recovery._binding({'candidate_sha':'f'*40, 'source_candidate_sha':'e'*40,
        'image_id':'sha256:'+'a'*64, 'acceptance_retirement_record_sha256':'b'*64, 'backup_id':'20260915t111822z'},
        {'context': {'retirement': {'acceptance_archive_sha256':'c'*64}}})
    record = {**binding, 'old_sha256':'d'*64, 'new_sha256':'e'*64,
              'started_at':'2026-09-15T12:00:00+00:00', 'completed_at':'2026-09-15T12:01:00+00:00',
              'passed':True, 'old_token_invalid':True, 'runtime_restored':True}
    recovery._validate_record(record,binding,final=True)
    record[field] = False if field == 'runtime_restored' else 'invalid'
    with pytest.raises(candidate.GateACandidateError):
        recovery._validate_record(record,binding,final=True)


async def test_rotation_recovery_rejects_old_token_reintroduced_on_another_table():
    await _seed_paid_failure()
    await qr.rotate({'mode':'apply', 'old_sha256':qr.digest('A'*32), 'new_token':'B'*32})
    verification = {'mode':'verify', 'old_sha256':qr.digest('A'*32), 'new_sha256':qr.digest('B'*32)}
    assert (await qr.rotate(verification))['current_sha256'] == qr.digest('B'*32)
    await StoreTable.create(table_no='T02', display_name='T02', qr_token='A'*32)
    before = await _read_footprint()
    with pytest.raises(ValueError,match='drift'):
        await qr.rotate(verification)
    assert await _read_footprint() == before


def test_paid_recovery_cli_does_not_echo_unrecognized_sensitive_arguments(monkeypatch, capsys):
    import sys
    secret = 'fixture-credential-must-not-be-echoed'
    monkeypatch.setattr(sys, 'argv', ['paid-recovery', '--unexpected', secret])
    with pytest.raises(SystemExit) as caught:
        recovery.main()
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert captured.err == 'Gate A paid recovery arguments are invalid\n'
