"""Refresh token rotation, revocation and login rate limiting."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import decode_access_token
from app.db.models.refresh_token import RefreshToken
from app.services import auth_session_service as svc

UTC = timezone.utc


# ── issuing ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_returns_an_access_token_and_an_opaque_refresh_token(db_session, user):
    tokens = await svc.issue_session(db_session, user)

    claims = decode_access_token(tokens.access_token)
    assert int(claims["sub"]) == user.id
    assert claims["tenant_id"] == user.tenant_id
    # The refresh token must not be a JWT — nothing should be derivable from it
    # without the database row.
    assert tokens.refresh_token.count(".") == 0


@pytest.mark.asyncio
async def test_access_token_is_short_lived(db_session, user):
    tokens = await svc.issue_session(db_session, user)
    claims = decode_access_token(tokens.access_token)
    lifetime = datetime.fromtimestamp(claims["exp"], UTC) - datetime.now(UTC)
    assert lifetime <= timedelta(minutes=svc.ACCESS_TOKEN_MINUTES + 1)


@pytest.mark.asyncio
async def test_refresh_token_is_stored_only_as_a_hash(db_session, user):
    tokens = await svc.issue_session(db_session, user)
    row = (await db_session.execute(select(RefreshToken))).scalar_one()
    assert row.token_hash != tokens.refresh_token
    assert tokens.refresh_token not in row.token_hash


# ── rotation ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_rotates_the_token(db_session, user):
    first = await svc.issue_session(db_session, user)
    second = await svc.rotate_refresh_token(db_session, first.refresh_token)

    assert second.refresh_token != first.refresh_token
    rows = (await db_session.execute(select(RefreshToken))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_a_rotated_token_cannot_be_used_again(db_session, user):
    first = await svc.issue_session(db_session, user)
    await svc.rotate_refresh_token(db_session, first.refresh_token)

    with pytest.raises(svc.InvalidRefreshToken):
        await svc.rotate_refresh_token(db_session, first.refresh_token)


@pytest.mark.asyncio
async def test_reusing_a_rotated_token_revokes_the_whole_family(db_session, user):
    """Replay means the token leaked; the thief may hold a newer one too.

    Killing only the presented token would leave the attacker's rotated copy
    working, so the entire chain descended from that login is revoked.
    """
    first = await svc.issue_session(db_session, user)
    second = await svc.rotate_refresh_token(db_session, first.refresh_token)

    with pytest.raises(svc.InvalidRefreshToken):
        await svc.rotate_refresh_token(db_session, first.refresh_token)

    # The legitimate holder's current token is now dead too — deliberately.
    with pytest.raises(svc.InvalidRefreshToken):
        await svc.rotate_refresh_token(db_session, second.refresh_token)


@pytest.mark.asyncio
async def test_expired_refresh_token_is_rejected(db_session, user):
    tokens = await svc.issue_session(db_session, user)
    row = (await db_session.execute(select(RefreshToken))).scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    with pytest.raises(svc.InvalidRefreshToken):
        await svc.rotate_refresh_token(db_session, tokens.refresh_token)


@pytest.mark.asyncio
async def test_unknown_refresh_token_is_rejected(db_session, user):
    with pytest.raises(svc.InvalidRefreshToken):
        await svc.rotate_refresh_token(db_session, "not-a-real-token")


# ── revocation ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logout_revokes_the_presented_token(db_session, user):
    tokens = await svc.issue_session(db_session, user)
    await svc.revoke_refresh_token(db_session, tokens.refresh_token, reason="logout")

    with pytest.raises(svc.InvalidRefreshToken):
        await svc.rotate_refresh_token(db_session, tokens.refresh_token)


@pytest.mark.asyncio
async def test_logout_leaves_other_sessions_alone(db_session, user):
    """Signing out of one device must not sign the user out everywhere."""
    laptop = await svc.issue_session(db_session, user)
    phone = await svc.issue_session(db_session, user)

    await svc.revoke_refresh_token(db_session, laptop.refresh_token, reason="logout")

    rotated = await svc.rotate_refresh_token(db_session, phone.refresh_token)
    assert rotated.refresh_token


@pytest.mark.asyncio
async def test_revoke_all_for_user_kills_every_session(db_session, user):
    laptop = await svc.issue_session(db_session, user)
    phone = await svc.issue_session(db_session, user)

    await svc.revoke_all_for_user(db_session, user.id, reason="password_change")

    for tokens in (laptop, phone):
        with pytest.raises(svc.InvalidRefreshToken):
            await svc.rotate_refresh_token(db_session, tokens.refresh_token)


@pytest.mark.asyncio
async def test_revoking_an_unknown_token_is_not_an_error(db_session, user):
    """Logout is idempotent: a client retrying it should not see a failure."""
    await svc.revoke_refresh_token(db_session, "never-existed", reason="logout")


# ── rate limiting ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_is_allowed_below_the_threshold(db_session):
    for _ in range(svc.MAX_FAILED_LOGINS - 1):
        await svc.record_failed_login(db_session, "demo", "admin", "10.0.0.1")
    assert await svc.is_login_blocked(db_session, "demo", "admin", "10.0.0.1") is False


@pytest.mark.asyncio
async def test_login_is_blocked_at_the_threshold(db_session):
    for _ in range(svc.MAX_FAILED_LOGINS):
        await svc.record_failed_login(db_session, "demo", "admin", "10.0.0.1")
    assert await svc.is_login_blocked(db_session, "demo", "admin", "10.0.0.1") is True


@pytest.mark.asyncio
async def test_old_failures_fall_outside_the_window(db_session):
    from app.db.models.refresh_token import LoginAttempt

    for _ in range(svc.MAX_FAILED_LOGINS):
        await svc.record_failed_login(db_session, "demo", "admin", "10.0.0.1")
    for row in (await db_session.execute(select(LoginAttempt))).scalars().all():
        row.attempted_at = datetime.now(UTC) - timedelta(
            minutes=svc.LOCKOUT_WINDOW_MINUTES + 1
        )
    await db_session.flush()

    assert await svc.is_login_blocked(db_session, "demo", "admin", "10.0.0.1") is False


@pytest.mark.asyncio
async def test_blocking_is_scoped_to_the_username(db_session):
    """One user's failures must not lock a colleague out."""
    for _ in range(svc.MAX_FAILED_LOGINS):
        await svc.record_failed_login(db_session, "demo", "admin", "10.0.0.1")
    assert await svc.is_login_blocked(db_session, "demo", "someone-else", "10.0.0.2") is False


@pytest.mark.asyncio
async def test_spraying_many_usernames_from_one_ip_is_blocked(db_session):
    """Per-username limits alone let an attacker walk a user list from one host."""
    for n in range(svc.MAX_FAILED_LOGINS_PER_IP):
        await svc.record_failed_login(db_session, "demo", f"user{n}", "10.0.0.9")
    assert await svc.is_login_blocked(db_session, "demo", "fresh-username", "10.0.0.9") is True


@pytest.mark.asyncio
async def test_successful_login_clears_the_failure_count(db_session):
    for _ in range(svc.MAX_FAILED_LOGINS - 1):
        await svc.record_failed_login(db_session, "demo", "admin", "10.0.0.1")
    await svc.clear_failed_logins(db_session, "demo", "admin")
    for _ in range(svc.MAX_FAILED_LOGINS - 1):
        await svc.record_failed_login(db_session, "demo", "admin", "10.0.0.1")
    assert await svc.is_login_blocked(db_session, "demo", "admin", "10.0.0.1") is False


@pytest.mark.asyncio
async def test_reuse_raises_the_variant_that_demands_a_commit(db_session, user):
    """Replay revokes the family, and that write must outlive the 401.

    get_db() rolls back the request transaction when an endpoint raises, so a
    revocation written on the way to an error is discarded unless the caller
    commits first — leaving the leaked token usable. The distinct exception type
    is how the service tells the endpoint that. Pinning the type here means a
    refactor that collapses it back into InvalidRefreshToken fails loudly rather
    than silently reintroducing the hole.

    Found by exercising the running container; the plain reuse test never rolls
    back, and the integration harness overrides get_db without its commit/rollback.
    """
    first = await svc.issue_session(db_session, user)
    second = await svc.rotate_refresh_token(db_session, first.refresh_token)
    await db_session.commit()

    with pytest.raises(svc.RefreshTokenRevocationWritten):
        await svc.rotate_refresh_token(db_session, first.refresh_token)

    # What the endpoint does on that exception.
    await db_session.commit()
    await db_session.rollback()

    with pytest.raises(svc.InvalidRefreshToken):
        await svc.rotate_refresh_token(db_session, second.refresh_token)
