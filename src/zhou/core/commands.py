from __future__ import annotations

from enum import Enum


class CommandType(str, Enum):
    NONE = "none"
    EXIT = "exit"
    SKILLS = "skills"
    TOOLS = "tools"
    MEMORY = "memory"


def parse_command(user_input: str) -> CommandType:
    normalized = user_input.strip().lower()
    if normalized in {"/exit", "/quit", "exit", "quit"}:
        return CommandType.EXIT
    if normalized in {"/skill", "/skills"}:
        return CommandType.SKILLS
    if normalized == "/tools":
        return CommandType.TOOLS
    if normalized.startswith("/memory"):
        return CommandType.MEMORY
    return CommandType.NONE
