"""Tests for The Cellar Cheesemonger tools.

Run with: uv run pytest
"""

import asyncio
import json
import random
from pathlib import Path

import pytest
from fastmcp import Client

import main

EM_DASH = chr(0x2014)

ROOT = Path(__file__).resolve().parent.parent


def names(items):
    return [c["name"] for c in items]


# ---------------------------------------------------------------- data
def test_catalog_shape():
    cheeses = main.load_cheeses()
    assert 12 <= len(cheeses) <= 25
    ids = [c["id"] for c in cheeses]
    assert len(ids) == len(set(ids))
    for c in cheeses:
        assert c["milk"] in main.MILKS
        assert c["style"] in main.STYLES
        assert 1 <= c["intensity"] <= 5
        assert c["price_tier"] in main.PRICE_PER_OZ_BY_TIER
        assert c["raw_milk"] in (True, False, None)
        assert set(c["pairs_with"]) == {"wine", "beer", "extras"}
        assert c["flavor_tags"]
    for required in ("Lincolnshire Poacher", "Prima Donna", "Langres"):
        assert required in names(cheeses)


# ---------------------------------------------------------------- find_cheese
def test_find_cheese_returns_three_ranked_picks():
    r = main.recommend(["nutty", "caramel"], 3)
    assert len(r["picks"]) == 3
    assert [p["rank"] for p in r["picks"]] == [1, 2, 3]
    assert r["picks"][0]["name"] == "Prima Donna"
    assert "caramel" in r["picks"][0]["matched_flavors"]
    scores = [p["score"] for p in r["picks"]]
    assert scores == sorted(scores, reverse=True)
    assert all(p["reasons"] for p in r["picks"])


def test_find_cheese_adventurousness_moves_intensity():
    mild = main.recommend([], 1)["picks"][0]
    bold = main.recommend([], 5)["picks"][0]
    assert mild["intensity"] < bold["intensity"]


def test_find_cheese_milk_filter():
    r = main.recommend(["tangy"], 2, milk="goat")
    assert r["picks"] and all(p["milk"] == "goat" for p in r["picks"])


def test_find_cheese_avoid_matches_milk_style_and_name():
    r = main.recommend(["salty"], 5, avoid=["blue", "sheep", "Parmigiano"])
    for p in r["picks"]:
        assert p["style"] != "blue"
        assert p["milk"] != "sheep"
        assert "Parmigiano" not in p["name"]


PREGNANCY_NOTE = "Pasteurized hard cheeses only. Confirm with the counter, and check with your doctor if unsure."


def test_find_cheese_pregnancy_safe():
    r = main.recommend(["creamy", "buttery"], 2, pregnancy_safe=True)
    assert r["picks"]
    assert all(p["style"] in ("hard", "semi-firm") and p["raw_milk"] is False for p in r["picks"])
    assert PREGNANCY_NOTE in r["notes"]
    # Soft, raw, and unconfirmed cheeses are all out, with reasons.
    assert {"Comté", "Fromager d'Affinois", "Humboldt Fog", "Drunken Goat"} <= set(names(r["excluded"]))
    assert all(e["reason"].startswith("pregnancy:") for e in r["excluded"])


def test_find_cheese_avoid_everything():
    r = main.recommend(["nutty"], 3, avoid=["cow", "goat", "sheep"])
    assert r["picks"] == []
    assert r["notes"]


def test_find_cheese_clamps_adventurousness():
    assert main.recommend([], 99)["query"]["adventurousness"] == 5


# ---------------------------------------------------------------- pair
def test_pair_cheese_returns_its_pairings():
    r = main.pairings_for("comte")  # no accent on purpose
    assert r["match_type"] == "cheese"
    assert r["cheese"]["name"] == "Comté"
    assert "Chardonnay" in r["pairs_with"]["wine"]


def test_pair_cheese_alias():
    assert main.pairings_for("parmesan")["cheese"]["id"] == "parmigiano-reggiano"


@pytest.mark.parametrize("item,expected", [
    ("pinot noir", "Mt Tam"),
    ("Pinot Noir", "Langres"),
    ("IPA", "Lincolnshire Poacher"),
    ("honey", "Humboldt Fog"),
    ("red wine", "Manchego"),
    ("rosé", "Drunken Goat"),
])
def test_pair_drink_or_food_returns_cheeses(item, expected):
    r = main.pairings_for(item)
    assert r["match_type"] == "pairing"
    assert expected in names(r["cheeses"])
    intensities = [c["intensity"] for c in r["cheeses"]]
    assert intensities == sorted(intensities)


def test_pair_unknown_item():
    r = main.pairings_for("kombucha")
    assert r["match_type"] == "unknown"
    assert "kombucha" in r["message"]
    assert r["try_examples"]


def test_pair_empty_item():
    assert main.pairings_for("   ")["match_type"] == "unknown"


# ---------------------------------------------------------------- build_board
def test_board_size_rules():
    assert main.board_size_for(1) == 3
    assert main.board_size_for(4) == 3
    assert main.board_size_for(5) == 4
    assert main.board_size_for(10) == 4
    assert main.board_size_for(11) == 5


@pytest.mark.parametrize("vibe", ["crowd-pleaser", "adventurous", "date-night", "spanish"])
def test_board_basics(vibe):
    r = main.plan_board(6, 200, vibe)
    assert r["ok"]
    board = r["tasting_order"]
    assert len(board) == 4
    assert [c["intensity"] for c in board] == sorted(c["intensity"] for c in board)
    assert len({c["style"] for c in board}) >= 3, "styles should vary"
    assert len({c["milk"] for c in board}) >= 2, "milks should vary"
    assert r["plating_tip"] and r["wine_picks"] and r["extras_to_buy"]
    assert not r["over_budget"]
    assert r["estimated_total_usd"] == pytest.approx(sum(c["estimated_cost_usd"] for c in board))


def test_board_portion_is_about_1_5_oz_per_guest():
    r = main.plan_board(8, 500, "crowd-pleaser")
    assert 1.5 <= r["ounces_per_guest"] <= 2.0


def test_spanish_board_leads_with_spain():
    r = main.plan_board(4, 200, "spanish")
    spanish = [c for c in r["tasting_order"] if "Spain" in c["origin"]]
    assert len(spanish) == 2


def test_adventurous_board_is_bolder_than_crowd_pleaser():
    adv = main.plan_board(6, 500, "adventurous")["tasting_order"]
    safe = main.plan_board(6, 500, "crowd-pleaser")["tasting_order"]
    assert sum(c["intensity"] for c in adv) > sum(c["intensity"] for c in safe)


def test_board_budget_slightly_low_swaps_and_explains():
    full = main.plan_board(6, 1000, "date-night")
    r = main.plan_board(6, full["estimated_total_usd"] - 5, "date-night")
    assert r["estimated_total_usd"] < full["estimated_total_usd"]
    assert r["adjustments"]
    assert any("Swapped" in a or "Dropped" in a for a in r["adjustments"])


def test_board_budget_far_too_low():
    r = main.plan_board(10, 5, "date-night")
    assert r["ok"]
    assert r["over_budget"] is True
    assert any("over budget" in n for n in r["notes"])
    assert any("portions" in a for a in r["adjustments"])
    assert len(r["tasting_order"]) >= main.MIN_BOARD_SIZE


def test_board_zero_guests():
    r = main.plan_board(0, 50, "crowd-pleaser")
    assert r["ok"] is False and "guest" in r["error"]


def test_board_zero_budget():
    assert main.plan_board(4, 0, "crowd-pleaser")["ok"] is False


def test_board_unknown_vibe():
    assert main.plan_board(4, 50, "goth")["ok"] is False


def test_board_avoid_everything():
    r = main.plan_board(4, 100, "crowd-pleaser", avoid=["cow", "goat", "sheep"])
    assert r["ok"] is False
    assert len(r["excluded"]) == len(main.CHEESES)


def test_board_small_pool_says_so():
    r = main.plan_board(20, 500, "crowd-pleaser", avoid=["cow"])
    assert len(r["tasting_order"]) == 4  # 2 goat + 2 sheep left
    assert any("Only 4 cheeses" in a for a in r["adjustments"])


SOFT_STYLES = {"fresh", "bloomy", "washed", "semi-soft", "blue"}


def test_demo_prompt_sorority_board():
    """12 guests, $60, someone hates blue, one friend is pregnant."""
    r = main.plan_board(12, 60, "crowd-pleaser", avoid=["blue cheese"], pregnancy_safe=True)
    assert r["ok"] and not r["over_budget"]
    board = r["tasting_order"]
    ids = {c["id"] for c in board}
    assert "fromager-daffinois" not in ids and "langres" not in ids
    assert not any(c["style"] in SOFT_STYLES for c in board)
    assert all(c["raw_milk"] is False for c in board)
    assert r["estimated_total_usd"] <= 60
    assert PREGNANCY_NOTE in r["notes"]
    # The catalog can't fill 5 safe slots, so it must say so instead of padding.
    assert r["short_board"] is True
    short = [n for n in r["notes"] if "pregnancy-safe rule" in n]
    assert short and all(c["name"] in short[0] for c in board)
    assert "baguette" not in r["extras_to_buy"]


SAFE_CASES = [
    dict(guests=g, budget_usd=b, vibe=v, avoid=a)
    for g in (1, 4, 12, 30)
    for b in (5, 60, 500)
    for v in ("crowd-pleaser", "adventurous", "date-night", "spanish")
    for a in (None, ["blue"], ["goat"])
]


@pytest.mark.parametrize("case", SAFE_CASES)
def test_every_pregnancy_safe_board_is_hard_and_pasteurized(case):
    r = main.plan_board(pregnancy_safe=True, **case)
    assert PREGNANCY_NOTE in r["notes"]
    for c in r.get("tasting_order", []):
        assert c["style"] in ("hard", "semi-firm"), c["name"]
        assert c["raw_milk"] is False, c["name"]


@pytest.mark.parametrize("flavors,adv", [(["creamy"], 1), (["funky"], 5), (["nutty", "caramel"], 3), ([], 2)])
def test_every_pregnancy_safe_pick_is_hard_and_pasteurized(flavors, adv):
    r = main.recommend(flavors, adv, pregnancy_safe=True)
    assert PREGNANCY_NOTE in r["notes"]
    for p in r["picks"]:
        assert p["style"] in ("hard", "semi-firm") and p["raw_milk"] is False, p["name"]


def test_pregnancy_safe_with_nothing_left_never_pads():
    r = main.plan_board(6, 100, "crowd-pleaser", avoid=["cow", "sheep"], pregnancy_safe=True)
    assert r["ok"] is False
    assert "pasteurized" in r["error"]
    assert "tasting_order" not in r


def test_pregnancy_rule_uses_more_safe_cheeses_when_they_exist():
    cheeses = json.loads(json.dumps(main.CHEESES))
    for c in cheeses:
        if c["id"] in ("manchego", "piave", "noord-hollander"):
            c["raw_milk"] = False
    r = main.plan_board(12, 60, "crowd-pleaser", ["blue"], True, cheeses=cheeses)
    assert {c["id"] for c in r["tasting_order"]} == {"prima-donna", "manchego", "piave", "noord-hollander"}
    assert not any(c["style"] in SOFT_STYLES for c in r["tasting_order"])


# ---------------------------------------------------------------- monger_story
def test_story_none_written_is_friendly():
    cheeses = json.loads(json.dumps(main.CHEESES))
    for c in cheeses:
        c["story"] = ""
    r = main.pick_story(cheeses)
    assert r["available"] is False
    assert "story" not in r and r["message"]


def test_story_skips_todo_empty_and_blank_entries():
    cheeses = json.loads(json.dumps(main.CHEESES))
    for i, c in enumerate(cheeses):
        c["story"] = ["", "TODO_KYLIE", "   ", " TODO_KYLIE "][i % 4]
    cheeses[3]["story"] = "The day the Langres crater overflowed."
    for seed in range(10):
        r = main.pick_story(cheeses, random.Random(seed))
        assert r["available"] and r["cheese"] == cheeses[3]["name"]
        assert "TODO" not in json.dumps(r)


# ---------------------------------------------------------------- MCP wiring
def test_mcp_server_end_to_end():
    async def run():
        async with Client(main.mcp) as client:
            tools = {t.name for t in await client.list_tools()}
            assert tools == {"find_cheese", "pair", "build_board", "monger_story"}
            res = await client.call_tool("build_board", {
                "guests": 12, "budget_usd": 60, "avoid": ["blue"], "pregnancy_safe": True})
            assert res.structured_content["ok"] is True
            res = await client.call_tool("pair", {"item": "IPA"})
            assert res.structured_content["match_type"] == "pairing"
            resources = await client.list_resources()
            assert "cellar://cheeses" in [str(r.uri) for r in resources]
            content = await client.read_resource("cellar://cheeses")
            assert "Lincolnshire Poacher" in content[0].text
            instructions = (client.initialize_result.instructions or "").lower()
            assert "unofficial demo" in instructions
            assert "not affiliated" in instructions
    asyncio.run(run())


# ---------------------------------------------------------------- style rules
def test_no_em_dashes_anywhere():
    for name in ("main.py", "README.md", "cheeses.json"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert EM_DASH not in text, f"em dash in {name}"
    outputs = json.dumps([
        main.plan_board(12, 60, "crowd-pleaser", ["blue"], True),
        main.plan_board(10, 5, "adventurous"),
        main.recommend(["funky"], 5),
        main.pairings_for("kombucha"),
        main.pick_story(),
    ], ensure_ascii=False)
    assert EM_DASH not in outputs


def test_never_speaks_for_the_cellar():
    """No first-person plural about the shop in data, docs, instructions, or output."""
    import re
    first_person = re.compile(r"\b(our|ours|we|we're|we've|us)\b", re.IGNORECASE)
    texts = {
        "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
        "INSTRUCTIONS": main.INSTRUCTIONS.replace('never as "we" or "our"', ""),
        "monger notes": " ".join(c["monger_note"] for c in main.CHEESES),
        "tool output": json.dumps([
            main.plan_board(12, 60, "crowd-pleaser", ["blue"], True),
            main.plan_board(6, 100, "crowd-pleaser", ["cow"], True),
            main.recommend(["nutty"], 3, pregnancy_safe=True),
            main.pairings_for("honey"), main.pairings_for("kombucha"),
            main.pick_story(),
        ]),
    }
    for where, text in texts.items():
        assert not first_person.search(text), f"first person in {where}: {first_person.search(text)}"


# ---------------------------------------------------------------- house favorites
def test_house_favorite_makes_crowd_pleaser_board():
    r = main.plan_board(12, 60, "crowd-pleaser", avoid=["blue"])
    favs = [c for c in r["tasting_order"] if c.get("house_favorite")]
    assert [c["id"] for c in favs] == ["fromager-daffinois"]
    assert not r["over_budget"]


def test_house_favorite_flag_only_on_favorites():
    flagged = [c["id"] for c in main.CHEESES if main.summary(c).get("house_favorite")]
    assert flagged == main.HOUSE_FAVORITES


# ---------------------------------------------------------------- drink picks
def test_demo_wine_picks_cover_the_whole_board():
    r = main.plan_board(12, 60, "crowd-pleaser", ["blue cheese"], True)
    board = {c["name"] for c in r["tasting_order"]}
    covered = {name for w in r["wine_picks"] for name in w["pairs_with"]}
    assert covered == board
    assert len({w["name"] for w in r["wine_picks"]}) == len(r["wine_picks"])


@pytest.mark.parametrize("vibe", ["crowd-pleaser", "adventurous", "date-night", "spanish"])
@pytest.mark.parametrize("guests", [3, 8, 15])
def test_each_drink_pick_reaches_a_new_cheese(vibe, guests):
    r = main.plan_board(guests, 500, vibe)
    board = [c["name"] for c in r["tasting_order"]]
    for key in ("wine_picks", "beer_picks"):
        covered: set[str] = set()
        for pick in r[key]:
            new = set(pick["pairs_with"]) - covered
            if covered != set(board):
                assert new, f"{key}: {pick['name']} adds no new cheese on {board}"
            covered |= set(pick["pairs_with"])


def test_broader_drink_name_covers_specific_one():
    board = [c for c in main.CHEESES if c["id"] in ("prima-donna", "noord-hollander")]
    picks = main.spread_picks(board, "wine", 1)
    assert picks[0]["name"] == "Port"
    assert set(picks[0]["pairs_with"]) == {"Prima Donna", "Noord Hollander"}


# ---------------------------------------------------------------- server instructions
def test_instructions_carry_exact_pregnancy_note_and_answer_rules():
    text = " ".join(main.INSTRUCTIONS.split())
    assert main.PREGNANCY_NOTE in text
    assert "as returned" in text and "do not change portions" in text
    assert "Never mention the server" in text


def test_board_carries_presentation_rules_for_the_model():
    r = main.plan_board(12, 60, "crowd-pleaser", ["blue cheese"], True)
    rules = " ".join(r["presentation_rules"])
    assert "word for word" in rules
    assert "1.5 oz per guest" in rules and "Do not raise or lower portions" in rules
    for w in r["wine_picks"]:
        assert w["name"] in rules
    # Rules are for the model; customer-facing notes must not contain them.
    assert not any("presentation" in n or "word for word" in n for n in r["notes"])


def test_light_portion_rule_matches_trimmed_board():
    r = main.plan_board(10, 5, "date-night")
    assert any("portions" in a for a in r["adjustments"])
    assert f"{main.LIGHT_OZ_PER_GUEST:g} oz per guest" in " ".join(r["presentation_rules"])


def test_pregnancy_only_raised_when_customer_raises_it():
    plain = " ".join(main.plan_board(12, 60, "crowd-pleaser", ["blue"])["presentation_rules"])
    assert "Do not bring up pregnancy" in plain
    assert "pregnancy_safe=true" in plain  # tells the model how to switch modes later
    safe = main.plan_board(12, 60, "crowd-pleaser", ["blue"], True)
    assert "Do not bring up pregnancy" not in " ".join(safe["presentation_rules"])
    assert main.PREGNANCY_NOTE in safe["notes"]
