"""Code that exists so the project can be driven without a real LLM.

`MODEL_BACKEND=fake` uses this for day-to-day development; the test suite uses it for
deterministic assertions. Nothing here talks to the network.
"""
