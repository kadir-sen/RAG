"""Vendored deterministic programme-analysis engines.

NOTICE: The `dcma` and `programme` subpackages are copied from
https://github.com/altunozan/delay-analysis-toolkit (private repository,
same product owner; copying explicitly authorized on 2026-07-06 — the
upstream repo carries no LICENSE file).

Local modifications, and nothing else:
  * absolute `from dcma.X` imports rewritten to package-relative,
  * LLM streaming backends removed from dcma/narrative.py so the ONLY LLM
    path in COAir remains src/llm_client.py.

Engines are pure stdlib (+openpyxl for the xlsx builders). The LLM must
never compute schedule metrics — these engines do; the LLM only narrates
their structured output under the narrative guard.
"""
