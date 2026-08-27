"""Sportsbet's account tools — the first surface in this catalogue that can move money.

Three tools, captured live 2026-08-27 by watching the account holder place a real bet:

    PUT  /apigw/acs/bets/combinations   sportsbet_price_slip    the authoritative price
    POST /apigw/acs/bets                sportsbet_place_bet     the write
    GET  /apigw/history/bets            sportsbet_bet_history   the read-back

The invariants below are not style preferences. Each one is a way this could take money
off someone incorrectly:

  * Placement takes an ASSERTED price, not a quote id, so the price must come from a
    price_slip call made immediately before — never a remembered one.
  * Placement answers 202 ACCEPTED, so a success response is not a placed bet.
  * A retried placement places the bet twice.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sportsdata_mcp.registry import _annotations_for
from sportsdata_mcp.spec_loader import load_spec

SPEC = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/sportsbet.yaml"


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC)


@pytest.fixture(scope="module")
def eps(spec):
    return {e.name: e for e in spec.endpoints}


# ─── the write ──────────────────────────────────────────────────────────


def test_placing_is_the_only_tool_in_the_write_group(eps, spec):
    """`.write` groups are reachable only by exact name — never a wildcard, preset or
    provider glob (test_write_tools pins that). Keeping exactly one tool in there means
    the thing that name enables is unambiguous."""
    writes = [e.name for e in spec.endpoints if e.group == "sportsbet.write"]
    assert writes == ["sportsbet_place_bet"]


def test_placing_is_marked_destructive_and_not_read_only(eps):
    """A client should confirm before calling this. The annotation is what makes that
    happen, and it is derived from method + read_only rather than asserted by hand."""
    a = _annotations_for(eps["sportsbet_place_bet"])
    assert a.readOnlyHint is False
    assert a.destructiveHint is True


def test_the_pricer_is_a_put_that_changes_nothing(eps):
    """It is a PUT, so the method alone would mark it destructive and make a client
    confirm before every price check. It prices a slip and stores nothing."""
    ep = eps["sportsbet_price_slip"]
    assert ep.method == "PUT"
    assert ep.read_only is True
    assert _annotations_for(ep).readOnlyHint is True


def test_the_hint_forbids_retrying_a_placement(eps):
    """The one rule that cannot bend. A placement that timed out may already have landed,
    and the retry is a second real bet."""
    hint = eps["sportsbet_place_bet"].response_hint or ""
    assert "NEVER RETRY" in hint
    assert "twice" in hint


def test_the_hint_says_202_is_not_a_placed_bet(eps):
    """202 Accepted means taken for processing. Treating it as confirmation is how a bet
    that never went on gets reported as placed."""
    hint = eps["sportsbet_place_bet"].response_hint or ""
    assert "202" in hint and "ACCEPTED, NOT 201" in hint
    assert "sportsbet_bet_history" in hint, "it must name the tool that confirms"


def test_the_hint_says_how_to_check_the_price_actually_received(eps):
    """betPotentialWin / totalStake is the accepted decimal price. Without this a bet can
    land at a price nobody agreed to and look like a success."""
    hint = eps["sportsbet_place_bet"].response_hint or ""
    assert "betPotentialWin" in hint and "totalStake" in hint
    assert "3.95" in hint, "the worked example is what makes it concrete"


def test_the_leg_shape_records_that_an_sgm_is_one_leg_with_parts(eps):
    """The single most confusable thing about this payload: a same game multi is
    betType SGL with ONE leg and several `parts`, and the combined price is replicated
    onto every part. Sent as a multi-leg bet it would be a different, longer bet."""
    d = next(p for p in eps["sportsbet_place_bet"].params if p.name == "betItems").description or ""
    assert "ONE LEG WITH SEVERAL `parts`" in d
    assert "REPLICATED ON EVERY PART" in d


def test_the_leg_shape_warns_about_the_two_id_spaces(eps):
    """Sportsbet has internal and external ids and the pricer wants external. Sending the
    internal pair from a topicLink returns HTTP 500 — the bug that was live in the
    comparator's Sportsbet quoter until it was fixed."""
    d = next(p for p in eps["sportsbet_place_bet"].params if p.name == "betItems").description or ""
    assert "NOT the internal ids" in d
    assert "103" in d and "17131" in d


# ─── the price that placement asserts ───────────────────────────────────


def test_the_pricer_hint_says_it_must_be_called_immediately_before(eps):
    """Placement takes no quote id, so the only defence against betting at a stale price
    is to price and place in the same breath."""
    hint = eps["sportsbet_price_slip"].response_hint or ""
    assert "immediately before placing" in hint
    assert "quote id" in hint
    assert "not a price" in hint


def test_the_pricer_hint_says_to_carry_the_fraction_not_the_decimal(eps):
    """Placement wants priceNum/priceDen. Re-deriving them from priceDecimal rounds, and
    a rounded price on a real bet is a real mismatch."""
    hint = eps["sportsbet_price_slip"].response_hint or ""
    assert "priceNum" in hint and "priceDecimal" in hint
    assert "rounds" in hint


def test_the_minimum_stake_is_recorded(eps):
    """0.01, from the verified slip — so a first live test bet is a cent."""
    assert "0.01" in (eps["sportsbet_price_slip"].response_hint or "")


# ─── auth ───────────────────────────────────────────────────────────────


def test_the_account_tier_is_a_public_client_on_the_refresh_grant(spec):
    """Sportsbet's CIAM lists "none" among token_endpoint_auth_methods_supported, so
    there is no client secret to hold — the refresh token is the entire credential."""
    a = spec.provider.auth["account"]
    assert a.grant == "refresh_token"
    assert a.refresh_token_env == "SPORTSBET_REFRESH_TOKEN"
    assert a.client_id_env is None and a.client_secret_env is None


def test_the_token_goes_in_sportsbets_own_header_not_authorization(spec):
    """The gateway reads `accesstoken`, bare. A Bearer prefix on an Authorization header
    would be ignored and every account call would fail as unauthenticated."""
    a = spec.provider.auth["account"]
    assert a.header == "accesstoken"
    assert a.value_prefix == ""


def test_the_account_tier_is_optional_so_keyless_installs_still_work(spec):
    """Every other Sportsbet tool is anonymous and must stay that way — adding an account
    tier must not make the provider require a credential it never needed."""
    assert spec.provider.auth["account"].optional is True
    assert spec.provider.auth["default"].type == "none"


@pytest.mark.parametrize("name", ["sportsbet_place_bet", "sportsbet_price_slip",
                                  "sportsbet_bet_history"])
def test_account_tools_use_the_account_tier(eps, name):
    assert eps[name].auth == "account"


@pytest.mark.parametrize("name", ["sportsbet_place_bet", "sportsbet_price_slip",
                                  "sportsbet_bet_history"])
def test_account_tools_send_sportsbets_required_headers(eps, name):
    """The gateway wants apptoken and customer-id alongside the token. Missing either is
    a 400 that looks like a malformed request rather than an auth failure."""
    hdrs = {p.wire_name for p in eps[name].params if p.in_ == "header"}
    assert {"apptoken", "customer-id", "channel"} <= hdrs


def test_no_anonymous_sportsbet_tool_was_switched_to_the_account_tier(spec):
    """The whole rest of this provider works with no credential. A tool quietly moved onto
    the account tier would break every keyless install."""
    account = {e.name for e in spec.endpoints if e.auth == "account"}
    assert account == {"sportsbet_place_bet", "sportsbet_price_slip", "sportsbet_bet_history"}


# ─── the engine change public clients needed ────────────────────────────


def test_a_public_client_omits_credentials_rather_than_sending_them_empty():
    """Sportsbet's token endpoint takes a refresh grant with NO client id and NO secret.
    Posting client_id="" is not the same request as posting no client_id, and the
    difference is a rejected grant — so absent credentials are dropped from the form body
    rather than blanked."""
    import httpx

    from sportsdata_mcp.auth.oauth import OAuthRefreshProvider
    from sportsdata_mcp.spec import AuthOAuthRefresh

    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["body"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "x", "expires_in": 900})

    spec = AuthOAuthRefresh(
        type="oauth_refresh", token_url="https://x.test/token", grant="refresh_token",
        refresh_token_env="T", header="accesstoken", value_prefix="")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OAuthRefreshProvider(spec, client, {"T": "the-refresh-token"})

    import asyncio
    header, value = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(provider.get())

    assert header == "accesstoken" and value == "x", "bare token, no Bearer prefix"
    assert "grant_type=refresh_token" in sent["body"]
    assert "client_id" not in sent["body"], "a public client must not send an empty client_id"
    assert "client_secret" not in sent["body"]


def test_an_optional_refresh_tier_is_gated_on_the_refresh_token_not_the_client_id():
    """The gate that decides "is this tier configured" used to look at client_id_env. For
    a public client that is always absent, so an optional tier would have gone permanently
    anonymous — silently, because optional tiers do not raise."""
    import httpx

    from sportsdata_mcp.config import Config
    from sportsdata_mcp.http_client import HTTPClient
    from sportsdata_mcp.spec_loader import load_spec

    spec = load_spec(SPEC)
    http = HTTPClient(spec.provider, Config())
    # No SPORTSBET_REFRESH_TOKEN configured -> anonymous, and NOT an error.
    provider = http._auth_provider("account")
    assert type(provider).__name__ == "NullAuthProvider"

    # With one configured, the real provider is built.
    http2 = HTTPClient(spec.provider, Config(secrets={"SPORTSBET_REFRESH_TOKEN": "t"}))
    assert type(http2._auth_provider("account")).__name__ == "OAuthRefreshProvider"
    assert isinstance(httpx.AsyncClient, type)
