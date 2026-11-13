# The Cellar Cheesemonger

An MCP server that puts a cheesemonger behind the counter of your AI assistant.

It imagines how **The Cellar**, the wine bar and cheese shop at 156 Avenida Del Mar in San Clemente, CA, could work on the agentic web. Ask Claude for a board for twelve, a cheese for your pinot, or something funky for an adventurous friend, and it answers from a real monger's catalog: tasting order, ounces, cost, and what to pour.

I built it as a former cheesemonger. The catalog, pairings, and monger notes come from time spent behind a cheese counter.

> **Unofficial demo.** This project is not affiliated with, endorsed by, or connected to The Cellar. Prices are rough planning estimates, not the shop's real prices, and nothing here reflects what is actually in the case.

## What it does

| Tool | What you give it | What you get back |
| --- | --- | --- |
| `find_cheese` | flavors you like, adventurousness 1 to 5, optional milk, things to avoid, pregnancy-safe flag | top 3 picks, each with a score and the reasons it was picked |
| `pair` | a cheese, a drink, or a snack ("Comté", "pinot noir", "IPA", "honey", "red wine") | the cheese's pairings, or every cheese that goes with the drink |
| `build_board` | guests, budget, vibe (`crowd-pleaser`, `adventurous`, `date-night`, `spanish`), avoid list, pregnancy-safe flag | 3 to 5 cheeses in tasting order, ounces each, estimated cost, wine and beer picks, extras, plating tip, and any budget trade-offs |
| `monger_story` | nothing | a story from behind the counter |

It also exposes the full catalog as the resource `cellar://cheeses`.

All tools are deterministic and return structured JSON. The server does the picking and the math; Claude writes the words.

## Run it locally

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python main.py          # serves http://localhost:8000/mcp
uv run pytest                  # run the tests
```

Set `PORT` to use a different port. To poke at it in the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP, URL: http://localhost:8000/mcp
```

Prices per ounce, portion sizes, and board size rules all live in the `CONFIG` block at the top of `main.py`.

## Deploy on Alpic

1. Push this repo to GitHub.
2. Go to [app.alpic.ai](https://app.alpic.ai) and sign in with GitHub.
3. Create a new project and pick this repository. Alpic detects the FastMCP server from `pyproject.toml` and `main.py`.
4. Deploy. Alpic gives you a public URL for the server. Copy it.

Every push to the main branch redeploys.

## Connect it to Claude

1. In Claude, open **Settings > Connectors**.
2. Choose **Add custom connector**.
3. Name it "The Cellar Cheesemonger" and paste your Alpic URL (the MCP endpoint ends in `/mcp`).
4. Start a new chat and turn the connector on from the tools menu.

## Try these prompts

1. "I'm hosting 12 sorority sisters Friday, $60 budget, someone hates blue cheese, one friend is pregnant. Build me a board and tell me what wine to grab."
2. "I've got a bottle of pinot noir open. What cheese should I pick up on the way home?"
3. "I love nutty, caramel-y cheeses but I want to be a little brave tonight, maybe a 4 out of 5. What should I try?"

## Project layout

```
main.py          server, tools, and the CONFIG block
cheeses.json     the catalog
tests/           pytest suite
pyproject.toml   dependencies (managed with uv)
.python-version  Python 3.13
```

## Disclaimer

The Cellar Cheesemonger is an independent, unofficial demo created to show what a local cheese shop could look like on the agentic web. It is not affiliated with or endorsed by The Cellar. Cheese details are given in good faith; raw milk status is marked unknown where it varies by producer. If anyone eating is pregnant or has allergies, confirm with the counter.
