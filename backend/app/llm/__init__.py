"""Claude Opus 4.8 generation layer (SPEC §5 prompt_strategy). Implemented by the **B2 agent**:
``client.py`` (AsyncAnthropic wrapper w/ prompt caching + structured outputs + usage logging),
``prompts/`` (cached pedagogy system prefixes per language), ``lesson_generator.py``,
``quiz_generator.py``, ``grader.py``, and ``orchestrator.py`` (the background-task entry).

Generators consume ONLY a validated StructuredIntent (never raw text). Stamp MODEL_ID/PROMPT_VERSION."""
