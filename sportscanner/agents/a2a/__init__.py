"""A2A (Agent2Agent) Sportscanner Agent, served on the main FastAPI app."""

from sportscanner.agents.a2a.server import mount_a2a

__all__ = ["mount_a2a"]
