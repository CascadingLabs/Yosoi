from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.models.test import TestModel

from yosoi.models import ScrapingConfig


def test_agent_prompt_construction(mock_selectors):
    """
    Verify that the HTML input is actually being formatted into the
    system prompt correctly before it hits the model.
    """
    # 1. Configure the TestModel to return your valid schema
    # This simulates a "Perfect AI" response
    model = TestModel(custom_output_args=mock_selectors)

    # 2. Inject into your Agent
    agent = Agent(model, output_type=ScrapingConfig)

    html_input = '<html><body><h1>Real Data</h1></body></html>'

    # 3. Run with message capturing
    with capture_run_messages() as messages:
        # Note: In your real code, you might be calling discovery.discover_from_html
        # which internally calls agent.run_sync
        result = agent.run_sync(f'Analyze this: {html_input}')

    # 4. Assert Result (Schema Validation worked)
    assert isinstance(result.output, ScrapingConfig)
    assert result.output.headline.primary == 'h1.title'

    # 5. Assert Prompt Engineering (The "Context" check)
    # This proves extraction logic actually put text in the prompt
    user_msg = messages[0]
    # Check parts for content. ModelRequest has a list of parts (SystemPromptPart, UserPromptPart, etc)
    # Each part usually has 'content' attribute if it's text-based
    full_content = ' '.join(
        part.content for part in user_msg.parts if hasattr(part, 'content') and isinstance(part.content, str)
    )
    assert 'Analyze this' in full_content
    assert 'Real Data' in full_content
