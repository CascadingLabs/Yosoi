"""Mocked-eval demo: ingest a tagged trace into local Langfuse.

Demonstrates the eval-tagging workflow documented at observability/evals-and-tagging.md.
Run with the local Langfuse stack running on http://localhost:3002.
"""

from __future__ import annotations

import os

from langfuse import Langfuse, propagate_attributes
from opentelemetry import trace

# Local Langfuse stack defaults from docker-compose.langfuse.yml.
os.environ.setdefault('LANGFUSE_PUBLIC_KEY', 'pk-lf-1234567890')
os.environ.setdefault('LANGFUSE_SECRET_KEY', 'sk-lf-1234567890')
os.environ.setdefault('LANGFUSE_HOST', 'http://localhost:3002')

client = Langfuse(should_export_span=lambda _s: True)
tracer = trace.get_tracer('yosoi-eval-demo')

with (
    propagate_attributes(
        session_id='eval-demo-session',
        user_id='shop.example.com',
        tags=['yosoi', 'eval', 'regression'],
    ),
    tracer.start_as_current_span('scrape shop.example.com/x') as root,
):
    root.set_attribute('url', 'https://shop.example.com/x')
    with tracer.start_as_current_span('fetch') as fetch:
        fetch.set_attribute('status', 200)
    with tracer.start_as_current_span('discover') as discover:
        discover.set_attribute('fields', 2)
    with tracer.start_as_current_span('extract') as extract:
        extract.set_attribute('items', 1)
    trace_id = format(root.get_span_context().trace_id, '032x')

client.flush()
print(f'TRACE_ID={trace_id}')
print(f'URL=http://localhost:3002/project/00000000-0000-0000-0000-000000000002/traces/{trace_id}')
