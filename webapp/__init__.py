"""Research Math Agent web app: a Claude-powered agent that solves the
*First Proof* benchmark problems, with a live step-by-step UI."""

from .agent import AgentConfig, run_agent

__all__ = ["AgentConfig", "run_agent"]
