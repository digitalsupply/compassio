"""启动强校验 SECRET_KEY（P0）：默认值/过短在非测试环境必须拒绝启动。"""

import pytest

from app.config import DEFAULT_SECRET_KEY, validate_settings


class _Stub:
    def __init__(self, secret_key: str, testing: bool = False):
        self.secret_key = secret_key
        self.testing = testing


def test_default_secret_key_is_rejected():
    with pytest.raises(RuntimeError):
        validate_settings(_Stub(DEFAULT_SECRET_KEY))


def test_short_secret_key_is_rejected():
    with pytest.raises(RuntimeError):
        validate_settings(_Stub("short-secret"))


def test_strong_secret_key_is_accepted():
    validate_settings(_Stub("x" * 48))


def test_tests_are_exempt():
    # 测试套件显式使用短密钥，不应因此无法启动。
    validate_settings(_Stub("test-secret", testing=True))
