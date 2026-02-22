"""Utility for loading prompts from markdown files."""

from pathlib import Path


def load_prompt(name: str) -> str:
    """Load a prompt from a .md file in the prompts directory.

    Args:
        name: Name of the prompt file (without extension)

    Returns:
        The content of the prompt file as a string.

    Raises:
        FileNotFoundError: If the prompt file does not exist.

    """
    # Get the directory where this file is located
    current_dir = Path(__file__).parent.parent
    prompt_path = current_dir / 'prompts' / f'{name}.md'

    if not prompt_path.exists():
        raise FileNotFoundError(f'Prompt file not found: {prompt_path}')

    return prompt_path.read_text(encoding='utf-8').strip()
