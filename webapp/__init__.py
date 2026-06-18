"""Research Math Agent web app: a Claude-powered agent that solves the
*First Proof* benchmark problems, with a live step-by-step UI."""

import site, sys
_user_site = site.getusersitepackages()
if _user_site not in sys.path:
    sys.path.insert(0, _user_site)

from .agent import AgentConfig, run_agent

__all__ = ["AgentConfig", "run_agent"]
