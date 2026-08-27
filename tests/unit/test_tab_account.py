"""TAB's account tools — the second book that can move money, and the better-designed one.

Captured live 2026-08-27 by watching the account holder place real bets (a single and a
same game multi, both HTTP 201). The agent did not place them.

    POST /v1/pricing-service/accounts/{n}/enquiry    tab_price_slip   mints decoTokens
    POST /v1/tab-betting-service/accounts/{n}/betslip tab_place_bet   the write

TAB is better than Sportsbet on both of the things that make automated placement risky,
and the tests below exist to keep those properties visible:

  * A decoToken BINDS a leg to a price TAB quoted, where Sportsbet takes a price the
    client asserts and hopes.
  * A transactionId is an IDEMPOTENCY KEY, so a timed-out placement can be safely asked
    about, where Sportsbet's can only be read back from history.

It is also synchronous — 201 Created, not Sportsbet's 202 Accepted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sportsdata_mcp.registry import _annotations_for, _build_body
from sportsdata_mcp.spec_loader import load_spec

SPEC = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/tab.yaml"


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC)


@pytest.fixture(scope="module")
def eps(spec):
    return {e.name: e for e in spec.endpoints}


# ─── the write ──────────────────────────────────────────────────────────


def test_placing_is_alone_in_the_write_group(spec):
    assert [e.name for e in spec.endpoints if e.group == "tab.write"] == ["tab_place_bet"]


def test_placing_is_destructive_and_pricing_is_not(eps):
    """Both are POSTs. Only one of them takes money, and a client should confirm before
    exactly one of them."""
    assert _annotations_for(eps["tab_place_bet"]).destructiveHint is True
    assert _annotations_for(eps["tab_price_slip"]).readOnlyHint is True


def test_placement_lives_on_a_different_host_from_everything_else(eps, spec):
    """Pricing is api.beta; the betslip is webapi. Getting this wrong is a 404 on a call
    that otherwise looks correct."""
    assert eps["tab_place_bet"].base == "webapi"
    assert spec.provider.base_urls["webapi"].startswith("https://webapi.tab.com.au")
    assert eps["tab_price_slip"].base == "default"


# ─── the two properties that make TAB safer ─────────────────────────────


def test_the_transaction_id_is_documented_as_an_idempotency_key(eps):
    """The whole reason a TAB placement can be recovered from and a Sportsbet one cannot.
    Reusing the id ASKS whether the bet landed; generating a new one PLACES A SECOND BET,
    and that distinction has to survive any future edit of this description."""
    d = next(p for p in eps["tab_place_bet"].params if p.name == "transactionId").description or ""
    assert "IDEMPOTENCY KEY" in d
    assert "SAME transactionId" in d
    assert "twice" in d


def test_every_leg_must_carry_a_deco_token(eps):
    """A decoToken binds the leg to a price TAB quoted. Without it there is nothing tying
    the bet to a real number, which is the position Sportsbet leaves you in permanently."""
    d = next(p for p in eps["tab_place_bet"].params if p.name == "bets").description or ""
    assert "EVERY LEG NEEDS ITS decoToken" in d
    assert "tab_price_slip" in d
    assert "stale" in d


def test_the_pricer_explains_that_it_is_what_mints_the_tokens(eps):
    """Otherwise it reads like a redundant second pricer next to tab_sgm_price."""
    hint = eps["tab_price_slip"].response_hint or ""
    assert "decoToken IS THE POINT" in hint
    assert "tab_sgm_price" in hint, "the relationship to the anonymous pricer must be stated"


def test_the_placement_hint_records_that_it_is_synchronous(eps):
    """201 Created, unlike Sportsbet's 202 Accepted. Worth stating because the read-back
    obligation genuinely differs between the two books."""
    hint = eps["tab_place_bet"].response_hint or ""
    assert "201 CREATED, AND SYNCHRONOUS" in hint
    assert "202" in hint, "the contrast with Sportsbet is the useful part"


def test_the_placement_hint_says_a_201_can_still_be_a_failure(eps):
    """There is a top-level `errors` and a per-bet `errors`. A 201 carrying a populated
    per-bet errors array is a bet that did not go on."""
    hint = eps["tab_place_bet"].response_hint or ""
    assert "errors` AT BOTH LEVELS" in hint
    assert "status code alone is not the answer" in hint


def test_the_placement_hint_says_how_to_check_the_price_received(eps):
    hint = eps["tab_place_bet"].response_hint or ""
    assert "expectedReturn" in hint and "tab_price_slip" in hint


# ─── auth ───────────────────────────────────────────────────────────────


def test_the_account_tier_is_auth0_and_separate_from_the_data_tier(spec):
    """TAB has TWO identity systems and conflating them would be a confusing failure: the
    `oauth` key is client-credentials against api.beta for public feeds and has nothing to
    do with a person; `account` is Auth0 and is the human's."""
    data, account = spec.provider.auth["oauth"], spec.provider.auth["account"]
    assert data.grant == "client_credentials"
    assert "api.beta.tab.com.au" in data.token_url
    assert account.grant == "refresh_token"
    assert account.token_url == "https://login.tab.com.au/oauth/token"
    assert account.refresh_token_env == "TAB_REFRESH_TOKEN"


def test_the_account_tier_is_a_public_client(spec):
    """Auth0 discovery lists "none" among token_endpoint_auth_methods_supported, so the
    refresh token is the entire credential — no secret to store or rotate."""
    a = spec.provider.auth["account"]
    assert a.client_id_env is None and a.client_secret_env is None


def test_the_account_tier_uses_a_plain_bearer_header(spec):
    """TAB wants an ordinary Authorization: Bearer, unlike Sportsbet's bespoke
    `accesstoken` header — so the defaults are correct and must stay."""
    a = spec.provider.auth["account"]
    assert a.header == "Authorization"
    assert a.value_prefix == "Bearer "


def test_the_account_tier_is_optional_so_keyless_installs_still_work(spec):
    assert spec.provider.auth["account"].optional is True


def test_only_the_two_account_tools_use_the_account_tier(spec):
    """Every other TAB tool is anonymous or on the public data tier. One quietly moved
    onto the account tier would demand a credential from installs that never needed one."""
    assert {e.name for e in spec.endpoints if e.auth == "account"} == {
        "tab_place_bet", "tab_price_slip"}


def test_the_jurisdiction_still_nests_into_clientDetails(eps):
    """Same envelope as tab_sgm_price — the dotted wire name that made that tool work has
    to be carried here too, or the enquiry is rejected."""
    body = _build_body(eps["tab_price_slip"], {
        "accountNumber": 1, "uuid": "u", "jurisdiction": "VIC", "channel": "web", "bets": [1]})
    assert body["clientDetails"] == {"jurisdiction": "VIC", "channel": "web"}
    assert "clientDetails.jurisdiction" not in body
