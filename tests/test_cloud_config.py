import json
import pytest
from backend.cloud_config import apply_private_environment


def test_private_config_sets_only_approved_runtime_variables(monkeypatch):
    monkeypatch.delenv('TEXT_API_KEY',raising=False)
    monkeypatch.setenv('ZHIKE_PRIVATE_CONFIG',json.dumps({'TEXT_API_KEY':'private-test-token','CLOUD_ADMIN_PASSWORD':'private-test-admin-password'}))
    apply_private_environment()
    import os
    assert os.environ['TEXT_API_KEY']=='private-test-token'
    assert 'ZHIKE_PRIVATE_CONFIG' not in os.environ


@pytest.mark.parametrize('raw',['not-json',json.dumps({'PYTHONPATH':'bad'}),json.dumps({'TEXT_API_KEY':False})])
def test_invalid_private_configuration_never_echoes_values(monkeypatch,raw):
    monkeypatch.setenv('ZHIKE_PRIVATE_CONFIG',raw)
    with pytest.raises(ValueError) as error:apply_private_environment()
    assert raw not in str(error.value)
