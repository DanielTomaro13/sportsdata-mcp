"""NBL schedule paging, and the two match tools that read NBL.com's game-centre feed.

Two failures here were silent, which is why they are pinned rather than just fixed:

* The schedule feed pages at 100 rows and a season is ~200, and its rows are not in date
  order. `nbl_schedule` never asked for more, so it returned an arbitrary 100: the back
  half of the season, with every game played so far missing, in a response that looked
  complete.
* The match feed's team stats are per QUARTER (period '0' is the full game, '1'-'4' the
  quarters). A projection that dropped `period` would merge them, and summing the rows
  would count every point twice without any error.
"""

from __future__ import annotations

import pytest

from sportsdata_mcp.project import apply_projection
from sportsdata_mcp.spec_loader import load_all_specs

NBL = next(s for s in load_all_specs() if s.provider.id == "nbl")
EP = {e.name: e for e in NBL.endpoints}


def _project(name: str, body: dict) -> dict:
    ep = EP[name]
    return apply_projection(body, pick=ep.response_pick, fields=ep.response_fields)


def test_the_schedule_asks_for_a_whole_season():
    """THE regression. A season is ~200 rows; the feed's own default is 100."""
    limit = next(p for p in EP["nbl_schedule"].params if p.name == "limit")
    assert limit.default and limit.default >= 300, (
        "nbl_schedule must request a whole season — without it the feed returns an "
        "arbitrary 100 rows and every game played so far can be missing")
    assert any(p.name == "offset" for p in EP["nbl_schedule"].params)


def test_trimming_the_schedule_keeps_every_documented_field():
    """The projection drops artwork, not data. These are the fields the tool's hint, the
    contract test and the integration test all rely on."""
    row = {k: 1 for k in ("id", "external_id", "start_time", "round", "match_type", "status",
                          "match_status", "home_score", "away_score", "attendance", "match_slug",
                          "match_title", "play_by_play", "match_bg", "odds", "primary_broadcaster")}
    row["home_team"] = {"id": 1, "name": "Sydney Kings", "team_code": "SYD", "team_logo": "u",
                        "color_primary": "#fff", "team_logo_blurhash": "x"}
    row["away_team"] = dict(row["home_team"])
    row["venue"] = {"name": "Sydney SuperDome", "address": None}
    out = _project("nbl_schedule", {"type": "t", "count": 1, "data": [row]})["data"][0]
    for k in ("id", "external_id", "start_time", "round", "match_status", "home_score",
              "away_score", "attendance", "match_slug", "match_title", "play_by_play"):
        assert k in out, f"nbl_schedule dropped documented field {k}"
    assert set(out["home_team"]) == {"id", "name", "team_code", "team_logo", "color_primary"}
    assert out["venue"] == {"name": "Sydney SuperDome"}
    for heavy in ("match_bg", "odds", "primary_broadcaster"):
        assert heavy not in out


def test_team_rows_keep_their_quarter():
    """Without `period` the per-quarter team rows are indistinguishable from the
    full-game row, and a sum over them doubles every total."""
    body = {"data": [{"team_match_statistics": [
        {"team": {"team_code": "SYD", "team_logo": "u"}, "period": "0", "points": 121},
        {"team": {"team_code": "SYD", "team_logo": "u"}, "period": "1", "points": 30},
    ]}]}
    rows = _project("nbl_match_boxscore", body)["data"][0]["team_match_statistics"]
    assert [r["period"] for r in rows] == ["0", "1"]
    assert rows[0]["team"] == {"team_code": "SYD"}


def test_the_two_match_tools_split_one_feed_by_size():
    """Both read /get/match/{id}. The box score must not carry the ~1.1 MB of
    play-by-play, and the play-by-play must not carry the box score."""
    assert EP["nbl_match_boxscore"].path == EP["nbl_match_playbyplay"].path == "/get/match/{matchId}"
    box = {f.split(".")[0] for f in EP["nbl_match_boxscore"].response_fields}
    pbp = {f.split(".")[0] for f in EP["nbl_match_playbyplay"].response_fields}
    assert "play_by_play" not in box
    assert not {"player_match_statistics", "team_match_statistics"} & pbp


@pytest.mark.parametrize("name", ["nbl_match_boxscore", "nbl_match_playbyplay"])
def test_match_tools_trim_the_repeated_team_objects(name):
    """Half of every raw play-by-play event is a repeated team object (logo URL and
    image placeholder). Only the team code survives."""
    body = {"data": [{"play_by_play": [{"action_id": 1, "team": {"team_code": "ILL", "team_logo": "u", "team_logo_blurhash": "x"}}],
                      "player_match_statistics": [{"points": 3, "team": {"team_code": "ILL", "team_logo": "u"}}]}]}
    out = _project(name, body)["data"][0]
    for section in ("play_by_play", "player_match_statistics"):
        for row in out.get(section, []):
            assert row["team"] == {"team_code": "ILL"}
