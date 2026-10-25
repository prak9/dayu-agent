"""Prompt 装配公共入口。"""

from alpha.prompting.prompt_composer import ComposedPrompt, PromptComposeContext, PromptComposer, PromptRenderer
from alpha.prompting.prompt_plan import PromptAssemblyPlan, PromptFragmentPlan, build_prompt_assembly_plan
from alpha.prompting.prompt_renderer import GuidanceParseError, PromptParseError, load_prompt, parse_when_tag_blocks, parse_when_tool_blocks
from alpha.prompting.scene_definition import (
    PromptFragmentType,
    PromptManifestError,
    SceneConversationDefinition,
    SceneDefinition,
    SceneFragmentDefinition,
    SceneModelDefinition,
    ToolSelectionMode,
    ToolSelectionPolicy,
    load_scene_definition,
    parse_scene_definition,
)
from alpha.prompting.tool_snapshot import PromptToolSnapshot, build_prompt_tool_snapshot

__all__ = [
    "build_prompt_assembly_plan",
    "build_prompt_tool_snapshot",
    "load_scene_definition",
    "parse_scene_definition",
    "ComposedPrompt",
    "PromptAssemblyPlan",
    "PromptToolSnapshot",
    "PromptComposeContext",
    "PromptComposer",
    "PromptParseError",
    "PromptFragmentPlan",
    "PromptFragmentType",
    "PromptManifestError",
    "PromptRenderer",
    "GuidanceParseError",
    "load_prompt",
    "parse_when_tag_blocks",
    "parse_when_tool_blocks",
    "SceneConversationDefinition",
    "SceneDefinition",
    "SceneFragmentDefinition",
    "SceneModelDefinition",
    "ToolSelectionMode",
    "ToolSelectionPolicy",
]
