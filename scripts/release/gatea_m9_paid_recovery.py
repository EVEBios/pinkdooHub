"""已付款失败后的单次受控恢复：重开完整 lineage，轮换 T01，绑定新验收基线。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
from typing import Any, Mapping

from scripts.release import gatea_candidate as candidate
from scripts.release import gatea_operations as gatea
from scripts.release import gatea_upgrade as upgrade

RECORD_SUFFIX = '.m9-paid-recovery.json'
BINDING_KEYS = {'predecessor_candidate_sha', 'failed_acceptance_sha256', 'rotation_record_sha256'}


def paid_context(*, release_record_dir: Path, deployment: Mapping[str, Any]) -> dict[str, Any] | None:
    """只读重开退休记录与 A/B/E 归档；旧候选继续使用原验收契约。"""
    if deployment.get('schema_version') != 2 or deployment.get('table_reconcile', {}).get('scanned', 0) == 0:
        return None
    predecessor = candidate._load_json(
        release_record_dir / f"{deployment['source_candidate_sha']}.existing-database-upgrade.json",
        'paid recovery predecessor',
    )
    if predecessor.get('schema_version') != 2:
        return None
    context = candidate._load_adoption_context(
        release_root=gatea.REPOSITORY_ROOT.parent, release_record_dir=release_record_dir,
        source_candidate_sha=deployment['source_candidate_sha'],
        lineage_source_candidate_sha=deployment['lineage_source_candidate_sha'],
        target_sha=deployment['candidate_sha'],
        acceptance_retirement_record_sha256=deployment['acceptance_retirement_record_sha256'],
        acceptance_record_dir=candidate.DEFAULT_ACCEPTANCE_RECORD_DIR,
        acceptance_failure_archive_dir=candidate.DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
        retirement_failure_archive_dir=candidate.DEFAULT_RETIREMENT_FAILURE_ARCHIVE_DIR,
    )
    retirement = context['retirement']
    if retirement['live_verification']['business_verification']['schema_version'] != 3:
        raise candidate.GateACandidateError('Paid recovery requires the paid terminal archive')
    failed, _, _ = candidate._validate_retireable_failed_acceptance(
        path=Path(retirement['acceptance_archive_path']),
        expected_candidate_sha=deployment['source_candidate_sha'],
        expected_sha256=retirement['acceptance_archive_sha256'],
    )
    return {'context': context, 'failed': failed}


def _read_record(path: Path, *, mode: int) -> tuple[dict[str, Any], str]:
    raw, _ = candidate._read_stable_protected_bytes(
        path, mode=mode, max_bytes=candidate.MAX_JSON_BYTES,
        description="Gate A paid recovery record",
    )
    try:
        value = json.loads(raw, object_pairs_hook=candidate._json_object_without_duplicates)
    except (ValueError, UnicodeError):
        raise candidate.GateACandidateError("Gate A paid recovery JSON is invalid") from None
    if not isinstance(value, dict):
        raise candidate.GateACandidateError("Gate A paid recovery JSON is invalid")
    return value, candidate._sha256_bytes(raw)


def _binding(deployment: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    return {'schema_version': 1, 'record_type': 'gatea-m9-paid-recovery',
            'candidate_sha': deployment['candidate_sha'], 'image_id': deployment['image_id'],
            'predecessor_candidate_sha': deployment['source_candidate_sha'],
            'failed_acceptance_sha256': context['context']['retirement']['acceptance_archive_sha256'],
            'acceptance_retirement_record_sha256': deployment['acceptance_retirement_record_sha256'],
            'backup_id': deployment['backup_id'], 'table_no': 'T01',
            'wallet_before': '155.00', 'wallet_after': '150.00', 'prior_closed_sessions': 1,
            'secret_values_recorded': False}


def _validate_record(record: Mapping[str, Any], binding: Mapping[str, Any], *, final: bool) -> None:
    keys = set(binding) | {'old_sha256', 'new_sha256', 'started_at'}
    if final:
        keys |= {'completed_at', 'passed', 'old_token_invalid', 'runtime_restored'}
    if (set(record) != keys or any(record.get(k) != v for k, v in binding.items())
            or any(candidate.SHA256_PATTERN.fullmatch(str(record.get(k, ''))) is None for k in ('old_sha256', 'new_sha256'))
            or record['old_sha256'] == record['new_sha256']
            or not candidate._is_utc_timestamp(record.get('started_at'))
            or (final and (not candidate._has_ordered_utc_interval(record)
                          or any(record.get(k) is not True for k in ('passed', 'old_token_invalid', 'runtime_restored'))))):
        raise candidate.GateACandidateError('Paid recovery record binding is invalid')


def acceptance_binding(*, release_record_dir: Path, deployment: Mapping[str, Any]) -> dict[str, str] | None:
    context = paid_context(release_record_dir=release_record_dir, deployment=deployment)
    if context is None:
        return None
    path = release_record_dir / (deployment['candidate_sha'] + RECORD_SUFFIX)
    if candidate._path_entry_exists(path.with_suffix('.json.pending'), 'paid recovery pending'):
        raise candidate.GateACandidateError('Paid recovery must finish before acceptance')
    record, digest = _read_record(path, mode=0o644)
    _validate_record(record, _binding(deployment, context), final=True)
    return {'predecessor_candidate_sha': record['predecessor_candidate_sha'],
            'failed_acceptance_sha256': record['failed_acceptance_sha256'],
            'rotation_record_sha256': digest}


def validate_acceptance_binding(payload: Mapping[str, Any], *, release_record_dir: Path, deployment: Mapping[str, Any]) -> None:
    expected = acceptance_binding(release_record_dir=release_record_dir, deployment=deployment)
    if (payload.get('paid_recovery') != expected
            or (expected is not None and payload.get('schema_version') != 2)
            or (expected is None and payload.get('schema_version') == 2)):
        raise candidate.GateACandidateError('Acceptance does not bind the paid recovery checkpoint')


def _task(values: Mapping[str, str], config_file: Path, secret_dir: Path, payload: dict) -> dict:
    result = gatea._run_compose(values=values, config_file=config_file, secret_dir=secret_dir,
        mode='loopback', arguments=('run', '--rm', '--no-deps', '-T', 'app', 'python', '-m', 'app.tasks.gatea_m9_qr_rotate'),
        input_text=json.dumps(payload), capture_output=True, check=False)
    try:
        data = json.loads(result.stdout)
        if (result.returncode != 0 or len(result.stdout) > 1024
                or set(data) != {'schema_version', 'table_no', 'current_sha256', 'released', 'secret_values_recorded'}
                or data['schema_version'] != 1 or data['table_no'] != 'T01' or data['released'] is not True
                or data['secret_values_recorded'] is not False
                or candidate.SHA256_PATTERN.fullmatch(str(data['current_sha256'])) is None):
            raise ValueError('invalid protocol')
    except (ValueError, TypeError):
        raise candidate.GateACandidateError('QR rotation task refused the checkpoint') from None
    return data


@candidate._serialized_operation
def recover(*, confirm_target_sha: str, confirm_failed_acceptance_sha256: str,
            config_file: Path = gatea.DEFAULT_CONFIG_FILE, secret_dir: Path = gatea.DEFAULT_SECRET_DIR,
            release_record_dir: Path = gatea.DEFAULT_RECORD_DIR,
            lock_file: Path | None = None, _termination_controller: candidate._MutationTerminationController | None = None) -> dict:
    target = gatea.REPOSITORY_ROOT.name
    if target != confirm_target_sha:
        raise candidate.GateACandidateError('Paid recovery target confirmation differs')
    candidate._require_execution_release(gatea.REPOSITORY_ROOT.parent, target)
    candidate._load_stage(release_root=gatea.REPOSITORY_ROOT.parent, release_record_dir=release_record_dir, target_sha=target)
    candidate._reject_unresolved_transition_journals(release_record_dir=release_record_dir,
        acceptance_record_dir=candidate.DEFAULT_ACCEPTANCE_RECORD_DIR)
    values = gatea._validated_inputs(config_file=config_file, secret_dir=secret_dir, mode='loopback', require_available_port=False)
    image_id = gatea.validate_app_image(values)
    if gatea._candidate_sha(values) != target:
        raise candidate.GateACandidateError('Paid recovery runtime differs from installed candidate')
    deployment = gatea._require_upgrade_record(record_dir=release_record_dir, candidate_sha=target, image_id=image_id)
    context = paid_context(release_record_dir=release_record_dir, deployment=deployment)
    if context is None:
        raise candidate.GateACandidateError('Paid recovery requires a paid predecessor')
    binding = _binding(deployment, context)
    if binding['failed_acceptance_sha256'] != confirm_failed_acceptance_sha256:
        raise candidate.GateACandidateError('Paid recovery failed acceptance confirmation differs')
    gatea._require_m9_upgrade_replay_record(record_dir=release_record_dir, candidate_sha=target, image_id=image_id, upgrade_record=deployment)
    path = release_record_dir / (target + RECORD_SUFFIX)
    pending_path = path.with_suffix('.json.pending')
    pending = _read_record(pending_path, mode=0o600)[0] if candidate._path_entry_exists(pending_path, 'paid recovery pending') else None
    final = _read_record(path, mode=0o644)[0] if candidate._path_entry_exists(path, 'paid recovery final') else None
    if pending:
        _validate_record(pending, binding, final=False)
    if final:
        _validate_record(final, binding, final=True)
        if pending and any(final.get(k) != v for k, v in pending.items()):
            raise candidate.GateACandidateError('Paid recovery publication differs')
    pinned = {**values, 'GATEA_APP_IMAGE': image_id}
    arguments = dict(values=pinned, config_file=config_file, secret_dir=secret_dir, mode='loopback')
    try:
        gatea._run_compose(**arguments, arguments=('stop', '--timeout', '30', *candidate.RETIREMENT_WRITER_SERVICES))
        rows = gatea._compose_ps(**arguments, services=candidate.M9_RUNTIME_SERVICES)
        upgrade._ensure_not_running(rows, *candidate.RETIREMENT_WRITER_SERVICES)
        gatea._ensure_services_healthy(rows, 'mysql', 'redis')
        candidate._failed_acceptance_business_verification(gatea=gatea, values=values,
            config_file=config_file, secret_dir=secret_dir, target_image_id=image_id,
            failed_acceptance=context['failed'])
        current = _task(pinned, config_file, secret_dir, {'mode': 'inspect'})['current_sha256']
        if final:
            if current != final['new_sha256']:
                raise candidate.GateACandidateError('Completed QR rotation has drifted')
        elif pending and current == pending['new_sha256']:
            pass  # 前次已提交但宿主未完成记录；不再次生成或写入 Token。
        else:
            if pending and current != pending['old_sha256']:
                raise candidate.GateACandidateError('Pending QR rotation has drifted')
            token = secrets.token_hex(16)
            pending = {**binding, 'old_sha256': current, 'new_sha256': candidate._sha256_bytes(token.encode()),
                       'started_at': pending['started_at'] if pending else candidate._utc_now()}
            if pending_path.exists():
                candidate._atomic_replace_json(pending_path, pending, 0o600)
            else:
                candidate._write_json_exclusive(pending_path, pending, 0o600)
            result = _task(pinned, config_file, secret_dir, {'mode': 'apply', 'old_sha256': current, 'new_token': token})
            del token
            if result['current_sha256'] != pending['new_sha256']:
                raise candidate.GateACandidateError('QR rotation did not commit the planned digest')
        checkpoint = final or pending
        verified = _task(pinned, config_file, secret_dir, {
            'mode': 'verify', 'old_sha256': checkpoint['old_sha256'], 'new_sha256': checkpoint['new_sha256'],
        })
        if verified['current_sha256'] != checkpoint['new_sha256']:
            raise candidate.GateACandidateError('QR verification did not match the durable checkpoint')
    finally:
        _termination_controller.begin_recovery()
        while True:
            try:
                gatea.app_up(config_file=config_file, secret_dir=secret_dir, record_dir=release_record_dir,
                    mode='loopback', wait_timeout=120, include_table_sweeper=True, allow_existing_gatea_publisher=True,
                    _start_new_session=True)
                break
            except (KeyboardInterrupt, SystemExit) as error:
                _termination_controller.remember_recovery_interruption(error)
    if final is None:
        final = {**pending, 'completed_at': candidate._utc_now(), 'passed': True,
                 'old_token_invalid': True, 'runtime_restored': True}
        _validate_record(final, binding, final=True)
        candidate._write_json_exclusive(path, final)
    pending_path.unlink(missing_ok=True)
    candidate._fsync_directory(release_record_dir)
    return final


class SecureArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, "Gate A paid recovery arguments are invalid\n")


def main() -> int:
    parser = SecureArgumentParser(description=__doc__)
    parser.add_argument('--confirm-target-sha', required=True)
    parser.add_argument('--confirm-failed-acceptance-sha256', required=True)
    args = parser.parse_args()
    try:
        result = recover(**vars(args))
    except Exception:
        print('Gate A paid recovery failed; retain its checkpoint and inspect safe diagnostics.')
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
