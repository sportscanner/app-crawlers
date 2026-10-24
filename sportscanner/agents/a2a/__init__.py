"""A2A (Agent2Agent) court-finder agent, served on the main FastAPI app."""

from sportscanner.agents.a2a.server import mount_a2a

__all__ = ["mount_a2a"]
