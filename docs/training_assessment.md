# Foodland Agent Training Assessment

## Verdict

The existing `tests/customer_situations_1000.jsonl` is useful as a broad smoke/eval set, but it is not sufficient by itself. It is mostly template-generated, so it does not cover enough real knowledge-base records, recipes, FAQ phrasing, cross-sell relationships, alternatives, and safety cases.

## Main Weaknesses Found

- Product ranking edge cases still need focused tests, especially `mate sushi ryzu?` and typo `gochuang`.
- FAQ cases must assert that no stale product cards remain visible after FAQ answers.
- Related-product intent must distinguish finished products from ingredients, e.g. `kimchi` versus `čo potrebujem na výrobu kimchi`.
- Recipe and magazine records from the knowledge database were underrepresented.
- Alternatives and cross-sell were not grounded enough in actual `CrossSell` and `Alternatives` tables.
- Allergy and dietary questions need safety assertions: answer from data and recommend verifying product detail.

## Added Dataset

Added `tests/knowledge_grounded_situations_600.jsonl`, generated from the real Foodland knowledge database:

- Products_AI
- FAQ
- Recipes
- Magazine
- CrossSell
- Alternatives
- IntentMapping

This should be used together with `tests/golden_questions.json` and `tests/customer_situations_1000.jsonl`.

## Recommended Next Step

Create an automated evaluator that calls `/chat` for each test case and reports:

- passed expected intent
- expected product included
- forbidden product not prioritized
- FAQ did not include product cards
- fallback did not hallucinate
