"""M15 制品必须绑定独立演练，保留逐步数据并完整恢复/清理。"""
import hashlib
import json
import zipfile

import pytest

from scripts.release import gatea_candidate as candidate
from tests.release.test_gatea_m15_snapshot import snapshot


def artifact_records(target='a'*40, head='b'*40, run='123', attempt=1):
    files = {f'state-{v}.json': snapshot(v) for v in range(9, 16)}
    files.update({
        'cleanup-report.json': {'schema_version':1,'record_type':'gatea-m9-m15-cleanup','passed':True,
            'owned_resources_removed':True,'containers':[],'volumes':[],'networks':[],'images':[],'temporary_paths':[]},
        'target-backup.json': {'passed':True,'candidate_sha':target,'backup_id':'20260915t150000z','m15_content_snapshot':files['state-15.json']},
        'target-restore.json': {'passed':True,'candidate_sha':target,'backup_id':'20260915t150000z',
            'm15_content_snapshot':files['state-15.json'], **{k:True for k in ('database_matches','images_match',
            'm15_content_matches','restore_app_ready','redis_started_empty','temporary_resources_removed')}},
        'runtime-verification.json': {'passed':True,'candidate_sha':target,'target_version':15,'loopback_only':True},
        'summary.json': {'schema_version':1,'record_type':'gatea-m9-m15-drill','passed':True,
            'source_sha':candidate.SOURCE_M9_SHA,'target_sha':target,'source_version':9,'target_version':15,
            'reported_pr_head_sha':head,'ci_run_id':run,'ci_run_attempt':attempt,'scope':'github-hosted-disposable-linux',
            'production_secrets_used':False,'persistent_gatea_authorized':False,'migration_steps':list(range(10,16)),
            'cleanup_passed':True},
    })
    return files


def write_artifact(path, files):
    raw = {name:json.dumps(value,sort_keys=True,separators=(',',':')).encode() for name,value in files.items() if name!='summary.json'}
    summary = {**files['summary.json'],'artifact_sha256':{name:hashlib.sha256(value).hexdigest() for name,value in raw.items()}}
    raw['summary.json']=json.dumps(summary,sort_keys=True,separators=(',',':')).encode()
    with zipfile.ZipFile(path,'w') as archive:
        for name,value in raw.items():archive.writestr(name,value)


@pytest.mark.parametrize('change',(None,'source','head','step','paid','restore','cleanup','sensitive','missing'))
def test_m15_artifact_rejects_wrong_run_data_or_incomplete_recovery(tmp_path,change):
    files=artifact_records()
    if change=='source':files['summary.json']['source_sha']='c'*40
    if change=='head':files['summary.json']['reported_pr_head_sha']='c'*40
    if change=='step':files['state-11.json']['m9_preserved']['payments']['sha256']='c'*64
    if change=='paid':files['state-9.json']['m9_preserved']['payments']['rows']=0
    if change=='restore':files['target-restore.json']['m15_content_matches']=False
    if change=='cleanup':files['cleanup-report.json']['containers']=['leftover']
    if change=='sensitive':files['runtime-verification.json']['password']='synthetic-sensitive-value'
    if change=='missing':del files['state-13.json']
    path=tmp_path/'artifact.zip';write_artifact(path,files)
    args=dict(target_sha='a'*40,source_head_sha='b'*40,run_id='123',run_attempt=1,target_version=15)
    if change is None:assert candidate._validate_ci_artifact(path,**args)['artifact_scan_passed'] is True
    else:
        with pytest.raises(candidate.GateACandidateError):candidate._validate_ci_artifact(path,**args)
