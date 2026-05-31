"""Agent and configuration for selector discovery.

Lazy (PEP 562): the LLM config + provider helpers live in ``config`` which pulls
pydantic-ai (~1.5s). Re-exporting eagerly meant importing *any* discovery
submodule (even light ones like ``mcp_draft``) paid that cost. Names now resolve
on first access. See ``CLAUDE.md`` ("Lazy loading").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.core.discovery.config import LLMBuilder as LLMBuilder
    from yosoi.core.discovery.config import LLMConfig as LLMConfig
    from yosoi.core.discovery.config import alibaba as alibaba
    from yosoi.core.discovery.config import anthropic as anthropic
    from yosoi.core.discovery.config import azure as azure
    from yosoi.core.discovery.config import bedrock as bedrock
    from yosoi.core.discovery.config import cerebras as cerebras
    from yosoi.core.discovery.config import claude_sdk as claude_sdk
    from yosoi.core.discovery.config import create_agent as create_agent
    from yosoi.core.discovery.config import create_model as create_model
    from yosoi.core.discovery.config import deepseek as deepseek
    from yosoi.core.discovery.config import fireworks as fireworks
    from yosoi.core.discovery.config import gemini as gemini
    from yosoi.core.discovery.config import github as github
    from yosoi.core.discovery.config import grok as grok
    from yosoi.core.discovery.config import groq as groq
    from yosoi.core.discovery.config import heroku as heroku
    from yosoi.core.discovery.config import huggingface as huggingface
    from yosoi.core.discovery.config import litellm as litellm
    from yosoi.core.discovery.config import mistral as mistral
    from yosoi.core.discovery.config import moonshotai as moonshotai
    from yosoi.core.discovery.config import nebius as nebius
    from yosoi.core.discovery.config import ollama as ollama
    from yosoi.core.discovery.config import openai as openai
    from yosoi.core.discovery.config import opencode as opencode
    from yosoi.core.discovery.config import openrouter as openrouter
    from yosoi.core.discovery.config import ovhcloud as ovhcloud
    from yosoi.core.discovery.config import provider as provider
    from yosoi.core.discovery.config import sambanova as sambanova
    from yosoi.core.discovery.config import together as together
    from yosoi.core.discovery.config import vercel as vercel
    from yosoi.core.discovery.config import vertexai as vertexai
    from yosoi.core.discovery.config import xai as xai
    from yosoi.core.discovery.field_agent import FieldDiscoveryAgent as FieldDiscoveryAgent
    from yosoi.core.discovery.mcp_orchestrator import MCPDiscoveryOrchestrator as MCPDiscoveryOrchestrator
    from yosoi.core.discovery.orchestrator import DiscoveryOrchestrator as DiscoveryOrchestrator

_CONFIG = 'yosoi.core.discovery.config'
_LAZY: dict[str, str] = {
    'FieldDiscoveryAgent': 'yosoi.core.discovery.field_agent',
    'MCPDiscoveryOrchestrator': 'yosoi.core.discovery.mcp_orchestrator',
    'DiscoveryOrchestrator': 'yosoi.core.discovery.orchestrator',
    **dict.fromkeys(
        (
            'LLMBuilder',
            'LLMConfig',
            'create_agent',
            'create_model',
            'alibaba',
            'anthropic',
            'azure',
            'bedrock',
            'cerebras',
            'claude_sdk',
            'deepseek',
            'fireworks',
            'gemini',
            'github',
            'grok',
            'groq',
            'heroku',
            'huggingface',
            'litellm',
            'mistral',
            'moonshotai',
            'nebius',
            'ollama',
            'openai',
            'opencode',
            'openrouter',
            'ovhcloud',
            'provider',
            'sambanova',
            'together',
            'vercel',
            'vertexai',
            'xai',
        ),
        _CONFIG,
    ),
}

__all__ = sorted(_LAZY)

__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
