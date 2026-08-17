"""
app/evaluation/conversation.py  -  V2.10 multi-turn (V2.9) evaluation

Runs a ConversationCase as an actual sequence of app.main.chat() calls
sharing ONE session_id (Section 29 - conversations are sequences, not
independent queries; contrast with app.evaluation.runner, which
deliberately isolates every GoldenCase into its own session). Every
turn's expectations are scored independently (Section 30 - "score every
transition, not only the final answer").
"""
from __future__ import annotations

from typing import Callable

from app.evaluation.schema import ConversationCase, ConversationCaseResult

SessionChatFn = Callable[[str, int, str], dict]


def run_conversation_case(case: ConversationCase, session_chat_fn: SessionChatFn) -> ConversationCaseResult:
    session_id = f"eval-conv-{case.session_id_prefix}"
    turn_results: list[dict] = []
    passed = True
    critical_failure = False
    context_contamination = False
    reference_errors = 0
    reasons: list[str] = []

    previous_product_ids: list[str] = []
    for index, turn in enumerate(case.turns):
        response = session_chat_fn(turn.message, 8, session_id) or {}
        products = response.get("products") or []
        product_ids = [p.get("id") for p in products if p.get("id")]

        turn_ok = True
        turn_reasons: list[str] = []

        def fail(reason: str) -> None:
            nonlocal turn_ok
            turn_ok = False
            turn_reasons.append(reason)

        if turn.expected_workflow is not None and response.get("workflow_id") != turn.expected_workflow:
            fail(f"turn {index}: expected workflow {turn.expected_workflow!r}, got {response.get('workflow_id')!r}")

        if turn.expected_intent is not None and response.get("intent") != turn.expected_intent:
            fail(f"turn {index}: expected intent {turn.expected_intent!r}, got {response.get('intent')!r}")

        if turn.expected_response_mode is not None and response.get("response_mode") != turn.expected_response_mode:
            fail(f"turn {index}: expected response_mode {turn.expected_response_mode!r}, got {response.get('response_mode')!r}")

        plan = response.get("recipe_shopping_plan")
        if turn.expected_recipe_plan_present is not None:
            has_plan = plan is not None
            if has_plan != turn.expected_recipe_plan_present:
                fail(f"turn {index}: expected recipe_plan_present={turn.expected_recipe_plan_present}, got {has_plan}")

        if turn.expected_active_recipe_id is not None:
            actual_dish = (plan or {}).get("dish_id")
            if actual_dish != turn.expected_active_recipe_id:
                fail(f"turn {index}: expected active recipe {turn.expected_active_recipe_id!r}, got {actual_dish!r}")

        if turn.expected_servings is not None:
            actual_servings = (plan or {}).get("requested_servings")
            if actual_servings != turn.expected_servings:
                fail(f"turn {index}: expected servings {turn.expected_servings}, got {actual_servings}")

        if turn.expected_products_nonempty is not None:
            if bool(product_ids) != turn.expected_products_nonempty:
                fail(f"turn {index}: expected products_nonempty={turn.expected_products_nonempty}, got {bool(product_ids)}")

        if turn.expected_reference_resolved_from_previous_index is not None:
            ref_index = turn.expected_reference_resolved_from_previous_index
            if ref_index < len(previous_product_ids):
                expected_id = previous_product_ids[ref_index]
                if not product_ids or product_ids[0] != expected_id:
                    reference_errors += 1
                    fail(
                        f"turn {index}: reference should resolve to {expected_id!r} "
                        f"(index {ref_index} of previous turn), got {product_ids[:1]!r}"
                    )
            else:
                fail(f"turn {index}: reference index {ref_index} out of range of previous turn ({len(previous_product_ids)} products)")

        if turn.expected_context_switch == "HARD":
            # Section 32 - context_contamination_rate: a genuine hard
            # switch must not carry ANY previous-turn product forward.
            if previous_product_ids and set(product_ids) & set(previous_product_ids):
                context_contamination = True
                fail(f"turn {index}: HARD switch expected, but {set(product_ids) & set(previous_product_ids)} carried over from the previous turn")
            if plan is not None:
                context_contamination = True
                fail(f"turn {index}: HARD switch expected, but a recipe_shopping_plan is still present")

        turn_results.append({
            "turn_index": index,
            "message": turn.message,
            "passed": turn_ok,
            "workflow_id": response.get("workflow_id"),
            "intent": response.get("intent"),
            "response_mode": response.get("response_mode"),
            "product_ids": product_ids,
            "reasons": turn_reasons,
        })

        if not turn_ok:
            passed = False
            if case.critical:
                critical_failure = True
            reasons.extend(turn_reasons)

        previous_product_ids = product_ids

    return ConversationCaseResult(
        case_id=case.id,
        passed=passed,
        critical_failure=critical_failure,
        turn_results=tuple(turn_results),
        context_contamination=context_contamination,
        reference_errors=reference_errors,
        reasons=tuple(reasons),
    )


def run_conversation_suite(cases: list[ConversationCase], session_chat_fn: SessionChatFn) -> list[ConversationCaseResult]:
    return [run_conversation_case(case, session_chat_fn) for case in cases]
