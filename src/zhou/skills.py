from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .session import Skill


FRONTMATTER_SEPARATOR = "---"
SKILL_FILENAMES = {"skill.md", "SKILL.md"}


@dataclass(slots=True)
class ParsedSkillDocument:
    metadata: dict[str, object]
    body: str


def discover_skills(cwd: Path) -> list[Skill]:
    skills_root = cwd / ".zhou" / "skills"
    if not skills_root.is_dir():
        return []

    skill_files = [
        path
        for path in skills_root.rglob("*")
        if path.is_file() and path.name in SKILL_FILENAMES
    ]
    skill_files.sort(key=lambda path: str(path.relative_to(skills_root)).lower())

    discovered: list[Skill] = []
    for skill_file in skill_files:
        relative_parent = skill_file.parent.relative_to(skills_root)
        fallback_name = relative_parent.as_posix()
        skill = load_skill(skill_file, fallback_name=fallback_name)
        if skill is not None:
            discovered.append(skill)

    return discovered


def load_skill(path: Path, fallback_name: str) -> Skill | None:
    content = path.read_text(encoding="utf-8")
    parsed = parse_skill_document(content)
    body = parsed.body.strip()
    if not body:
        return None

    metadata = parsed.metadata
    name = str(metadata.get("name") or fallback_name).strip() or fallback_name
    title = str(metadata.get("title") or name).strip() or name
    description = str(metadata.get("description") or "").strip()
    tags_value = metadata.get("tags") or []
    tags = [str(tag).strip() for tag in tags_value if str(tag).strip()]

    return Skill(
        name=name,
        title=title,
        description=description,
        tags=tags,
        body=body,
        path=path,
    )


def parse_skill_document(content: str) -> ParsedSkillDocument:
    stripped = content.lstrip()
    if not stripped.startswith(FRONTMATTER_SEPARATOR):
        return ParsedSkillDocument(metadata={}, body=content)

    lines = stripped.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_SEPARATOR:
        return ParsedSkillDocument(metadata={}, body=content)

    closing_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == FRONTMATTER_SEPARATOR:
            closing_index = index
            break

    if closing_index is None:
        return ParsedSkillDocument(metadata={}, body=content)

    metadata_lines = lines[1:closing_index]
    body_lines = lines[closing_index + 1 :]
    metadata = parse_frontmatter_lines(metadata_lines)
    body = "\n".join(body_lines)
    return ParsedSkillDocument(metadata=metadata, body=body)


def parse_frontmatter_lines(lines: list[str]) -> dict[str, object]:
    metadata: dict[str, object] = {}
    current_list_key: str | None = None

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("- ") and current_list_key:
            value = stripped[2:].strip()
            metadata.setdefault(current_list_key, [])
            cast_list = metadata[current_list_key]
            if isinstance(cast_list, list):
                cast_list.append(value)
            continue

        current_list_key = None
        if ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        normalized_key = key.strip().lower()
        normalized_value = value.strip()

        if not normalized_value:
            metadata[normalized_key] = []
            current_list_key = normalized_key
        else:
            metadata[normalized_key] = normalized_value.strip('"').strip("'")

    return metadata


def build_skill_system_prompt(skills: list[Skill]) -> str:
    if not skills:
        return ""

    lines = [
        "以下 skills 在本次会话中持续启用，请始终遵循。",
        "",
    ]

    for skill in skills:
        lines.append(f"Skill: {skill.title}")
        if skill.description:
            lines.append(f"Description: {skill.description}")
        lines.append(skill.body.strip())
        lines.append("")

    return "\n".join(lines).strip()
