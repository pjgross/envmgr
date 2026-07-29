"""Settings must refuse to hand a production deployment an insecure signing key."""
import pytest

from app.core.config import INSECURE_DEV_SECRET_KEY, Settings


def test_shipped_dev_secret_key_is_rejected_outside_debug():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(DEBUG=False, SECRET_KEY=INSECURE_DEV_SECRET_KEY)


def test_shipped_dev_secret_key_is_allowed_in_debug():
    settings = Settings(DEBUG=True, SECRET_KEY=INSECURE_DEV_SECRET_KEY)
    assert settings.SECRET_KEY == INSECURE_DEV_SECRET_KEY


def test_real_secret_key_is_accepted_outside_debug():
    settings = Settings(DEBUG=False, SECRET_KEY="a-real-deployment-secret")
    assert settings.SECRET_KEY == "a-real-deployment-secret"


def test_debug_is_off_by_default():
    """DEBUG drives SQL echo (app/db/base.py) — it must not default on."""
    assert Settings.model_fields["DEBUG"].default is False
