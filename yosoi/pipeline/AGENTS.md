# Pipeline Agent Guide

## Context
The `pipeline` is the central nervous system of Yosoi. It ties together fetching, cleaning, discovery, and validation into a coherent workflow.
*Note: This directory is intended to house the future refactored pipeline components.*

## Objectives
1. **Orchestration**: Manage the sequence of steps (Fetch -> Clean -> Discover -> Validate).
2. **Resilience**: Handle failures gracefully (e.g., retrying failed LLM calls, handling bot detection).
3. **Observability**: Provide deep visibility into what the agent is doing via `logfire` and `rich`.

## Flow Control
- **caching**: Always check `SelectorStorage` before hitting the LLM unless `--force` is used.
- **Validation**: If validation fails, the pipeline should decide whether to retry discovery or fallback to heuristics.
- **Heuristics**: If the site is simple or an RSS feed, skip the LLM and use heuristic selectors.

## Refactoring Goals
The current `pipeline.py` is a monolithic class. Future work should aim to:
- Split `SelectorDiscoveryPipeline` into smaller, composable units.
- Isolate retry logic from business logic.
