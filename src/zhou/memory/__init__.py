"""zhou.memory package.

Keep package import side effects minimal so submodules like
`zhou.memory.enrichment` can be imported from `session.py` without eagerly
loading `manager.py` / `model.py` and triggering circular imports.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "MemoryScope",
    "MemoryKind",
    "MemoryClass",
    "MemoryRecord",
    "MemorySearchHit",
    "MemorySearchResult",
    "MemoryManager",
    "NullMemoryManager",
    "Mem0MemoryManager",
    "format_memory_context",
    "build_memory_key",
    "apply_enriched_result",
    "MemoryDecisionDraft",
    "MemoryModelClient",
    "MemoryModelJob",
    "MemoryModelOutput",
    "MemoryModelWorker",
    "EnrichedTurnResult",
    "derive_turn_tags",
    "derive_memory_candidates",
    "derive_folder_promotions",
]


def __getattr__(name: str):
    if name in {
        "MemoryScope",
        "MemoryKind",
        "MemoryClass",
        "MemoryRecord",
        "MemorySearchHit",
        "MemorySearchResult",
        "MemoryManager",
        "NullMemoryManager",
        "Mem0MemoryManager",
        "format_memory_context",
        "build_memory_key",
        "apply_enriched_result",
    }:
        module = import_module(".manager", __name__)
        return getattr(module, name)
    if name in {
        "MemoryDecisionDraft",
        "MemoryModelClient",
        "MemoryModelJob",
        "MemoryModelOutput",
        "MemoryModelWorker",
        "EnrichedTurnResult",
    }:
        module = import_module(".model", __name__)
        return getattr(module, name)
    if name in {
        "derive_turn_tags",
        "derive_memory_candidates",
        "derive_folder_promotions",
    }:
        module = import_module(".enrichment", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
