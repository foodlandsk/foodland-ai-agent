"""
app/evaluation  -  Sprint V2.10 Evaluation, Quality & Recommendation
Intelligence Engine

Observes the running Foodland AI Advisor (app.main.chat()) and scores it
against a grounded golden dataset. This package NEVER changes runtime
behaviour - no ranking weights, taxonomy rules, or recipe mappings are
read or written by anything here. See docs/evaluation-engine.md.

Central rule (Section 115/116/117/118): the evaluator exists to find
where Mei is wrong, not to produce a high score. Semantic correctness
(real taxonomy classification) always outranks lexical similarity, and a
single aggregate never hides a domain-specific critical failure.
"""
