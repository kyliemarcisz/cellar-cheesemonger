"""The Cellar Cheesemonger: an unofficial demo MCP server.

Built by a former cheesemonger to show what The Cellar (wine bar and cheese
shop, 156 Avenida Del Mar, San Clemente, CA) could look like on the agentic
web. Not affiliated with or endorsed by The Cellar.

Every tool is deterministic and returns structured JSON. The model writes the
prose; this server only does the picking, scoring, and math.
"""

from __future__ import annotations

import difflib
import json
import math
import os
import random
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

# =============================================================================
# CONFIG: edit freely.
# The prices below are ESTIMATES for demo math only. They are NOT The Cellar's
# real prices and say nothing about what is in stock.
# =============================================================================
PRICE_PER_OZ_BY_TIER: dict[str, float] = {
    "$": 1.50,   # about $24 per pound
    "$$": 2.25,  # about $36 per pound
    "$$$": 3.00,  # about $48 per pound
}
OZ_PER_GUEST = 1.5          # standard board portion, all cheeses combined
LIGHT_OZ_PER_GUEST = 1.0    # fallback portion when the budget is tight
MIN_OZ_PER_CHEESE = 2.0     # smallest piece worth cutting at the counter
OZ_ROUNDING = 0.5           # round each piece up to this many ounces
MIN_BOARD_SIZE = 2          # never drop below this many cheeses
BOARD_STAPLES = ["a baguette or plain water crackers"]


def board_size_for(guests: int) -> int:
    """3 cheeses for up to 4 guests, 4 for up to 10, 5 for more."""
    if guests <= 4:
        return 3
    if guests <= 10:
        return 4
    return 5
# =============================================================================
# End of CONFIG
# =============================================================================

DATA_PATH = Path(__file__).parent / "cheeses.json"
TODO_MARKER = "TODO_KYLIE"
STYLES = ["fresh", "bloomy", "semi-soft", "semi-firm", "hard", "washed", "blue"]
MILKS = ["cow", "goat", "sheep", "mixed"]
PREGNANCY_NOTE = (
    "Filtered to cheeses listed as pasteurized. Producers and batches vary, "
    "so confirm with the counter before serving anyone who is pregnant."
)

# Plain-language words people use, mapped to catalog values.
AVOID_ALIASES = {
    "bleu": "blue", "blues": "blue", "goats": "goat", "sheeps": "sheep",
    "cows": "cow", "stinky": "washed", "washed rind": "washed",
    "parmesan": "parmigiano reggiano",
}
FLAVOR_ALIASES = {
    "stinky": "funky", "pungent": "funky", "sharp": "tangy", "bright": "tangy",
    "rich": "buttery", "mushroom": "mushroomy", "salt": "salty",
    "sweet": "sweet", "fruit": "fruity", "lemony": "citrus", "peppery": "spicy",
}
CHEESE_ALIASES = {
    "parmesan": "parmigiano-reggiano", "parm": "parmigiano-reggiano",
    "point reyes blue": "point-reyes-original-blue", "delice": "delice-de-bourgogne",
    "mount tam": "mt-tam", "queso de murcia al vino": "drunken-goat",
}
PAIRING_ALIASES = {
    "red wine": ["cabernet", "merlot", "zinfandel", "pinot noir", "tempranillo", "rioja",
                 "garnacha", "barbera", "nebbiolo", "sangiovese", "lambrusco", "bordeaux"],
    "white wine": ["chardonnay", "sauvignon blanc", "riesling", "chablis",
                   "gewurztraminer", "chasselas", "vin jaune"],
    "bubbly": ["sparkling", "champagne", "prosecco", "franciacorta"],
    "bubbles": ["sparkling", "champagne", "prosecco", "franciacorta"],
    "rose": ["rose"],
    "dessert wine": ["port", "sauternes", "late-harvest"],
    "cab": ["cabernet"], "zin": ["zinfandel"], "sav blanc": ["sauvignon blanc"],
    "cider": ["hard cider"], "stout": ["stout"], "jam": ["jam"],
}

PLATING_TIPS = {
    "crowd-pleaser": "Pull the cheeses 45 minutes before guests arrive and lay them clockwise from mildest to boldest so nobody starts with the loudest one.",
    "adventurous": "Give the funky and blue cheeses their own knives and plenty of space, and set them last in the clockwise order.",
    "date-night": "Keep it small and let the soft cheeses come fully to room temperature, about an hour out of the fridge, so they slump a little on the board.",
    "spanish": "Cut the Manchego into thin triangles, set membrillo and marcona almonds in little piles, and serve everything at room temperature.",
}

VIBES = Literal["crowd-pleaser", "adventurous", "date-night", "spanish"]


# ----------------------------------------------------------------------------
# Data helpers
# ----------------------------------------------------------------------------
def load_cheeses(path: Path = DATA_PATH) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["cheeses"]


CHEESES: list[dict[str, Any]] = load_cheeses()


def norm(text: str) -> str:
    """Lowercase, strip accents and possessives, collapse whitespace."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("'s", "").replace("’s", "")
    return re.sub(r"\s+", " ", text).strip()


def has_phrase(needle: str, haystack: str) -> bool:
    """Whole-word phrase match on normalized text."""
    return bool(needle) and re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


def price_per_oz(cheese: dict[str, Any]) -> float:
    return PRICE_PER_OZ_BY_TIER[cheese["price_tier"]]


def tasting_key(cheese: dict[str, Any]) -> tuple[int, int]:
    return (cheese["intensity"], STYLES.index(cheese["style"]))


def summary(cheese: dict[str, Any]) -> dict[str, Any]:
    """Compact view of a cheese for tool output."""
    out = {
        "id": cheese["id"],
        "name": cheese["name"],
        "origin": cheese["origin"],
        "milk": cheese["milk"],
        "style": cheese["style"],
        "intensity": cheese["intensity"],
        "flavor_tags": cheese["flavor_tags"],
        "price_tier": cheese["price_tier"],
        "raw_milk": cheese["raw_milk"],
    }
    if cheese.get("monger_note") and cheese["monger_note"] != TODO_MARKER:
        out["monger_note"] = cheese["monger_note"]
    return out


def _avoid_term(term: str) -> str:
    t = norm(term)
    t = re.sub(r"\b(cheeses?|milk|rind)\b", "", t).strip()
    return AVOID_ALIASES.get(t, t)


def is_avoided(cheese: dict[str, Any], avoid: list[str] | None) -> str | None:
    """Return the avoid term that knocks this cheese out, or None.

    A term matches the milk ("goat"), the style ("blue"), a flavor tag
    ("funky"), or part of the name ("roquefort").
    """
    for raw in avoid or []:
        t = _avoid_term(raw)
        if not t:
            continue
        if t in (cheese["milk"], cheese["style"]) or t in cheese["flavor_tags"]:
            return raw
        if has_phrase(t, norm(cheese["name"])) or t == cheese["id"]:
            return raw
    return None


def filter_pool(
    cheeses: list[dict[str, Any]],
    avoid: list[str] | None = None,
    pregnancy_safe: bool = False,
    milk: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Apply hard filters. Returns (kept, excluded-with-reason)."""
    kept, excluded = [], []
    want_milk = _avoid_term(milk) if milk else None
    for c in cheeses:
        reason = None
        if want_milk and c["milk"] != want_milk:
            reason = f"not {want_milk} milk"
        elif (hit := is_avoided(c, avoid)) is not None:
            reason = f"avoid: {hit}"
        elif pregnancy_safe and c["raw_milk"] is not False:
            reason = "raw milk" if c["raw_milk"] else "pasteurization unconfirmed"
        if reason:
            excluded.append({"name": c["name"], "reason": reason})
        else:
            kept.append(c)
    return kept, excluded


# ----------------------------------------------------------------------------
# 1. find_cheese
# ----------------------------------------------------------------------------
def _flavor_matches(wanted: list[str], tags: list[str]) -> list[str]:
    hits = []
    for w in wanted:
        w = FLAVOR_ALIASES.get(norm(w), norm(w))
        for tag in tags:
            if w and (w == tag or w in tag or tag in w) and tag not in hits:
                hits.append(tag)
    return hits


def recommend(
    flavors: list[str],
    adventurousness: int,
    milk: str | None = None,
    avoid: list[str] | None = None,
    pregnancy_safe: bool = False,
    cheeses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cheeses = CHEESES if cheeses is None else cheeses
    adv = max(1, min(5, int(adventurousness)))
    pool, excluded = filter_pool(cheeses, avoid, pregnancy_safe, milk)
    notes = [PREGNANCY_NOTE] if pregnancy_safe else []

    scored = []
    for c in pool:
        matched = _flavor_matches(flavors or [], c["flavor_tags"])
        gap = abs(c["intensity"] - adv)
        score = 3 * len(matched) + 2 * (4 - gap)
        reasons = []
        if matched:
            reasons.append(f"Matches your flavors: {', '.join(matched)}")
        if gap == 0:
            reasons.append(f"Intensity {c['intensity']}/5 lines up with your adventurousness")
        else:
            direction = "milder" if c["intensity"] < adv else "bolder"
            reasons.append(f"Intensity {c['intensity']}/5, a bit {direction} than you asked for")
        scored.append((score, c, matched, reasons))

    scored.sort(key=lambda s: (-s[0], abs(s[1]["intensity"] - adv), s[1]["name"]))
    picks = [
        {"rank": i + 1, "score": score, "matched_flavors": matched, "reasons": reasons,
         **summary(c), "pairs_with": c["pairs_with"]}
        for i, (score, c, matched, reasons) in enumerate(scored[:3])
    ]
    if not picks:
        notes.append("Nothing in the case fits those filters. Try loosening the avoid list or milk choice.")
    return {
        "query": {"flavors": flavors, "adventurousness": adv, "milk": milk,
                  "avoid": avoid or [], "pregnancy_safe": pregnancy_safe},
        "picks": picks,
        "excluded": excluded,
        "notes": notes,
    }


# ----------------------------------------------------------------------------
# 2. pair
# ----------------------------------------------------------------------------
def find_cheese_by_name(item: str, cheeses: list[dict[str, Any]]) -> dict[str, Any] | None:
    q = norm(item)
    q = re.sub(r"\bcheese\b", "", q).strip()
    if not q:
        return None
    by_id = {c["id"]: c for c in cheeses}
    if q in CHEESE_ALIASES and CHEESE_ALIASES[q] in by_id:
        return by_id[CHEESE_ALIASES[q]]
    for c in cheeses:
        name = norm(c["name"])
        if q in (name, c["id"]) or has_phrase(name, q) or (len(q) >= 5 and has_phrase(q, name)):
            return c
    names = {norm(c["name"]): c for c in cheeses}
    close = difflib.get_close_matches(q, list(names), n=1, cutoff=0.85)
    return names[close[0]] if close else None


def pairings_for(item: str, cheeses: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cheeses = CHEESES if cheeses is None else cheeses
    if not item or not norm(item):
        return {"match_type": "unknown", "item": item, "message": "Tell me a cheese, drink, or snack to pair."}

    cheese = find_cheese_by_name(item, cheeses)
    if cheese:
        return {"match_type": "cheese", "item": item, "cheese": summary(cheese),
                "pairs_with": cheese["pairs_with"]}

    q = norm(item)
    terms = PAIRING_ALIASES.get(q, [q])
    matches = []
    for c in cheeses:
        hits = []
        for category in ("wine", "beer", "extras"):
            for entry in c["pairs_with"][category]:
                e = norm(entry)
                if any(has_phrase(t, e) or has_phrase(e, t) for t in terms):
                    hits.append({"category": category, "entry": entry})
        if hits:
            matches.append({**summary(c), "matched_on": hits})

    if matches:
        matches.sort(key=tasting_key)
        return {"match_type": "pairing", "item": item, "count": len(matches),
                "cheeses": matches, "order": "mildest to boldest"}

    vocab = sorted({e for c in cheeses for cat in c["pairs_with"].values() for e in cat}
                   | {c["name"] for c in cheeses})
    suggestions = difflib.get_close_matches(item, vocab, n=3, cutoff=0.5)
    return {
        "match_type": "unknown",
        "item": item,
        "message": f"I don't have a pairing on file for '{item}'.",
        "did_you_mean": suggestions,
        "try_examples": ["pinot noir", "IPA", "honey", "red wine", "Comté"],
    }


# ----------------------------------------------------------------------------
# 3. build_board
# ----------------------------------------------------------------------------
SPANISH_WINES = ("tempranillo", "rioja", "sherry", "garnacha", "albarino", "cava")


def vibe_score(c: dict[str, Any], vibe: str) -> float:
    tags = set(c["flavor_tags"])
    wines = " ".join(norm(w) for w in c["pairs_with"]["wine"])
    i = c["intensity"]
    if vibe == "adventurous":
        return 1.5 * i + (1.5 if c["style"] in ("washed", "blue") else 0) + (1 if tags & {"funky", "spicy", "meaty"} else 0)
    if vibe == "date-night":
        return (4 - abs(i - 2.5)) + (2 if c["style"] in ("bloomy", "washed") else 0) \
            + (1 if ("champagne" in wines or "sparkling" in wines) else 0) + (1 if tags & {"creamy", "buttery"} else 0)
    if vibe == "spanish":
        return (6 if "spain" in norm(c["origin"]) else 0) + (2 if any(w in wines for w in SPANISH_WINES) else 0) \
            + (1 if c["milk"] in ("sheep", "goat") else 0) + (3 - abs(i - 2.5)) * 0.5
    # crowd-pleaser
    return 5 - 1.5 * abs(i - 2) + (1 if tags & {"buttery", "creamy", "nutty", "caramel", "sweet"} else 0) \
        - (2 if c["style"] in ("washed", "blue") else 0)


def _diverse_score(c: dict[str, Any], chosen: list[dict[str, Any]], vibe: str) -> float:
    same_style = sum(x["style"] == c["style"] for x in chosen)
    same_milk = sum(x["milk"] == c["milk"] for x in chosen)
    return vibe_score(c, vibe) - 3 * same_style - 1.5 * same_milk


def _pick(pool: list[dict[str, Any]], n: int, vibe: str) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    remaining = list(pool)
    while remaining and len(chosen) < n:
        best = max(remaining, key=lambda c: _diverse_score(c, chosen, vibe))
        chosen.append(best)
        remaining.remove(best)
    return chosen


def _ounces_each(guests: int, n: int, oz_per_guest: float) -> float:
    raw = guests * oz_per_guest / n
    return max(MIN_OZ_PER_CHEESE, math.ceil(raw / OZ_ROUNDING) * OZ_ROUNDING)


def _cost(board: list[dict[str, Any]], oz_each: float) -> float:
    return round(sum(round(price_per_oz(c) * oz_each, 2) for c in board), 2)


def plan_board(
    guests: int,
    budget_usd: float,
    vibe: str = "crowd-pleaser",
    avoid: list[str] | None = None,
    pregnancy_safe: bool = False,
    cheeses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cheeses = CHEESES if cheeses is None else cheeses
    if guests is None or guests < 1:
        return {"ok": False, "error": "Need at least 1 guest to build a board."}
    if budget_usd is None or budget_usd <= 0:
        return {"ok": False, "error": "Budget must be more than $0."}
    if vibe not in PLATING_TIPS:
        return {"ok": False, "error": f"Unknown vibe '{vibe}'. Pick one of: {', '.join(PLATING_TIPS)}."}

    pool, excluded = filter_pool(cheeses, avoid, pregnancy_safe)
    if not pool:
        return {"ok": False, "error": "Every cheese in the case is ruled out by those filters.",
                "excluded": excluded}

    adjustments: list[str] = []
    target = board_size_for(guests)
    board = _pick(pool, target, vibe)
    if len(board) < target:
        adjustments.append(f"Only {len(board)} cheeses fit your filters, so the board has {len(board)} instead of {target}.")

    oz_per_guest = OZ_PER_GUEST
    oz_each = _ounces_each(guests, len(board), oz_per_guest)

    # Step 1: swap the priciest cheese for the best cheaper one, repeatedly.
    while _cost(board, oz_each) > budget_usd:
        swapped = False
        for old in sorted(board, key=lambda c: -price_per_oz(c)):
            others = [c for c in board if c is not old]
            cheaper = [c for c in pool if c not in board and price_per_oz(c) < price_per_oz(old)]
            if cheaper:
                new = max(cheaper, key=lambda c: _diverse_score(c, others, vibe))
                board[board.index(old)] = new
                adjustments.append(f"Swapped {old['name']} ({old['price_tier']}) for {new['name']} ({new['price_tier']}) to save money.")
                swapped = True
                break
        if not swapped:
            break

    # Step 2: drop the priciest cheese if that actually lowers the total.
    while _cost(board, oz_each) > budget_usd and len(board) > MIN_BOARD_SIZE:
        priciest = max(board, key=price_per_oz)
        smaller = [c for c in board if c is not priciest]
        new_oz = _ounces_each(guests, len(smaller), oz_per_guest)
        if _cost(smaller, new_oz) >= _cost(board, oz_each):
            break
        board, oz_each = smaller, new_oz
        adjustments.append(f"Dropped {priciest['name']} to stay closer to budget.")

    # Step 3: lighter portions.
    if _cost(board, oz_each) > budget_usd and oz_per_guest > LIGHT_OZ_PER_GUEST:
        oz_per_guest = LIGHT_OZ_PER_GUEST
        oz_each = _ounces_each(guests, len(board), oz_per_guest)
        adjustments.append(f"Cut portions to {LIGHT_OZ_PER_GUEST} oz per person to fit the budget.")

    total = _cost(board, oz_each)
    over = total > budget_usd
    board.sort(key=tasting_key)

    wine_counts = Counter(w for c in board for w in c["pairs_with"]["wine"])
    beer_counts = Counter(b for c in board for b in c["pairs_with"]["beer"])
    staples = norm(" ".join(BOARD_STAPLES))
    extra_counts = Counter(e for c in board for e in c["pairs_with"]["extras"]
                           if not has_phrase(norm(e), staples))

    def top(counter: Counter, k: int) -> list[dict[str, Any]]:
        return [{"name": name, "pairs_with": [c["name"] for c in board if name in
                 c["pairs_with"]["wine"] + c["pairs_with"]["beer"] + c["pairs_with"]["extras"]]}
                for name, _ in counter.most_common(k)]

    notes = []
    if pregnancy_safe:
        notes.append(PREGNANCY_NOTE)
    if over:
        notes.append(f"Even trimmed down, this board runs about ${total - budget_usd:.2f} over budget. "
                     f"Plan on about ${total:.2f}, or fewer guests.")
    notes.append("Prices are rough estimates for planning, not The Cellar's actual prices.")

    return {
        "ok": True,
        "guests": guests,
        "vibe": vibe,
        "budget_usd": budget_usd,
        "estimated_total_usd": total,
        "over_budget": over,
        "budget_remaining_usd": round(budget_usd - total, 2),
        "ounces_per_guest": round(oz_each * len(board) / guests, 2),
        "tasting_order": [
            {"position": i + 1, **summary(c), "ounces": oz_each,
             "estimated_cost_usd": round(price_per_oz(c) * oz_each, 2)}
            for i, c in enumerate(board)
        ],
        "wine_picks": top(wine_counts, 3),
        "beer_picks": top(beer_counts, 2),
        "extras_to_buy": BOARD_STAPLES + [e["name"] for e in top(extra_counts, 4)],
        "plating_tip": PLATING_TIPS[vibe],
        "adjustments": adjustments,
        "excluded": excluded,
        "notes": notes,
    }


# ----------------------------------------------------------------------------
# 4. monger_story
# ----------------------------------------------------------------------------
def pick_story(cheeses: list[dict[str, Any]] | None = None, rng: random.Random | None = None) -> dict[str, Any]:
    cheeses = CHEESES if cheeses is None else cheeses
    ready = [c for c in cheeses if c.get("story") and c["story"].strip() != TODO_MARKER]
    if not ready:
        return {"available": False,
                "message": "The monger hasn't written any stories yet. Check back soon."}
    c = (rng or random).choice(ready)
    out = {"available": True, "cheese": c["name"], "origin": c["origin"], "story": c["story"]}
    if c.get("monger_note") and c["monger_note"] != TODO_MARKER:
        out["monger_note"] = c["monger_note"]
    return out


# ----------------------------------------------------------------------------
# MCP server
# ----------------------------------------------------------------------------
INSTRUCTIONS = """\
The Cellar Cheesemonger is an UNOFFICIAL demo built by a former cheesemonger. \
It imagines how The Cellar (a wine bar and cheese shop at 156 Avenida Del Mar, \
San Clemente, CA) could work on the agentic web. It is not affiliated with or \
endorsed by The Cellar. Prices are rough planning estimates, not real prices, \
and the catalog says nothing about current inventory.

How to use the tools:
- find_cheese: personal recommendations from flavors and adventurousness.
- pair: pairings for a cheese, or cheeses for a wine, beer, or snack.
- build_board: a full board for a party, with ounces, cost, wine, and extras. \
If anyone is pregnant, pass pregnancy_safe=true. Put dislikes in avoid.
- monger_story: a story from behind the counter.

The tools return structured data. Write the answer in a warm, knowledgeable \
cheesemonger voice, present boards in tasting order (mild to strong), and \
always pass along any notes about pregnancy or budget. Avoid em dashes."""

mcp = FastMCP("The Cellar Cheesemonger", instructions=INSTRUCTIONS)

READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}


@mcp.tool(annotations={**READ_ONLY, "idempotentHint": True})
def find_cheese(
    flavors: Annotated[list[str], Field(description="Flavors the guest likes, e.g. ['nutty', 'caramel'] or ['funky']")],
    adventurousness: Annotated[int, Field(ge=1, le=5, description="1 = play it safe, 5 = bring me the stinkiest thing you have")],
    milk: Annotated[str | None, Field(description="Only this milk: cow, goat, sheep, or mixed")] = None,
    avoid: Annotated[list[str] | None, Field(description="Things to rule out: a milk ('goat'), a style ('blue'), a flavor ('funky'), or a cheese name")] = None,
    pregnancy_safe: Annotated[bool, Field(description="Only cheeses listed as pasteurized")] = False,
) -> dict:
    """Recommend the top 3 cheeses for someone's taste, with reasons for each pick."""
    return recommend(flavors, adventurousness, milk, avoid, pregnancy_safe)


@mcp.tool(annotations={**READ_ONLY, "idempotentHint": True})
def pair(
    item: Annotated[str, Field(description="A cheese ('Comté'), a drink ('pinot noir', 'IPA', 'red wine'), or a snack ('honey')")],
) -> dict:
    """Find pairings. Give a cheese to get its wines, beers, and extras; give a drink or food to get the cheeses that go with it."""
    return pairings_for(item)


@mcp.tool(annotations={**READ_ONLY, "idempotentHint": True})
def build_board(
    guests: Annotated[int, Field(description="Number of people eating")],
    budget_usd: Annotated[float, Field(description="Total cheese budget in US dollars")],
    vibe: Annotated[VIBES, Field(description="crowd-pleaser, adventurous, date-night, or spanish")] = "crowd-pleaser",
    avoid: Annotated[list[str] | None, Field(description="Things to rule out: a milk, a style ('blue'), a flavor, or a cheese name")] = None,
    pregnancy_safe: Annotated[bool, Field(description="Set true if anyone eating is pregnant; keeps only cheeses listed as pasteurized")] = False,
) -> dict:
    """Build a cheese board in tasting order with ounces, estimated cost, wine and beer picks, extras, and a plating tip. Trims to fit the budget and explains any changes."""
    return plan_board(guests, budget_usd, vibe, avoid, pregnancy_safe)


@mcp.tool(annotations={**READ_ONLY, "idempotentHint": False})
def monger_story() -> dict:
    """Share a random story from behind the cheese counter."""
    return pick_story()


@mcp.resource("cellar://cheeses", name="cheese-catalog", mime_type="application/json",
              description="The full cheese catalog behind this server.")
def cheese_catalog() -> str:
    return DATA_PATH.read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), path="/mcp")
