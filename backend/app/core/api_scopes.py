"""Canonical vocabulary of API-key scopes.

Before this module existed, `ApiKeyCreate.scopes` was a free-form
`list[str]` with nothing validating it server-side, and every
`api_key_auth(required_scope=...)` call site repeated its scope as a string
literal. A typo'd scope on a key at create time saved happily, the plaintext
key was shown once, and every call made with it then 403'd on a
scope-missing message that gave no hint a typo was the cause.

`KNOWN_SCOPES` is now the one place the vocabulary lives:
`ApiKeyCreate` validates against it (see
`app/api/v1/schemas/api_key.py`), and every `required_scope=` call site
reads its value from the constants below rather than repeating the string
— so the checker and the vocabulary cannot drift apart.

The frontend's `ApiKeyCreateDialog.tsx` scope picker is generated from
`frontend/src/constants/apiKeyScopes.json`, whose keys and labels
`tests/test_api_scope_contract.py` asserts match this dict exactly — the
same pattern `docs/pagination.md`'s sort whitelists use for
`sortWhitelists.json`.
"""

WEBHOOKS_DEPLOYMENT = "webhooks:deployment"
WEBHOOKS_RELEASE = "webhooks:release"

# scope -> human label/description
KNOWN_SCOPES: dict[str, str] = {
    WEBHOOKS_DEPLOYMENT: "CI/CD deployment webhook",
    WEBHOOKS_RELEASE: "Release gate readiness webhook",
}
