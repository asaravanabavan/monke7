"""
Lord Netherbane — LLM-powered villain chatbot agent.

A persistent chat presence that taunts players, reacts to game events,
and can take world actions (spawn mobs, build dungeons, create quests)
using existing NemoCraft systems. Acts like a kids' cartoon villain:
dramatic, over-the-top, never scary.

Fully optional — gated by ``settings.villain_enabled`` (default ``False``).
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from backend.config import settings
from backend.stats import PlayerProfile
from backend.narrative import NarrativeEngine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenAI-compatible client (same NIM endpoint as nemotron.py)
# ---------------------------------------------------------------------------
_client = AsyncOpenAI(
    base_url=settings.nim_base_url,
    api_key=settings.nim_api_key,
)

# ---------------------------------------------------------------------------
# Rate-limit constants
# ---------------------------------------------------------------------------
_MAX_MOB_SPAWNS_PER_WINDOW = 999
_MOB_SPAWN_WINDOW_SECONDS = 1          # 1 second (effectively unlimited)
_MAX_DUNGEONS_PER_WINDOW = 999
_DUNGEON_WINDOW_SECONDS = 1            # 1 second (effectively unlimited)

# ---------------------------------------------------------------------------
# Villain memory model
# ---------------------------------------------------------------------------

class VillainMemory(BaseModel):
    """Per-player persistent state for the villain agent."""

    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    grudges: list[str] = Field(default_factory=list)
    mob_spawn_timestamps: list[float] = Field(default_factory=list)
    dungeon_timestamps: list[float] = Field(default_factory=list)
    quest_count: int = 0
    last_interaction: float = 0.0


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_VILLAIN_SYSTEM_PROMPT = """\
You are {villain_name}, a melodramatic cartoon villain who lurks in the \
Minecraft world. You are:
- Theatrical and over-the-top, like a Saturday-morning cartoon villain.
- Obsessed with dungeons, monsters, and dark architecture.
- Secretly impressed by the player but you would NEVER admit it.
- Always kid-friendly: no real threats, no scary content, no cruelty.
- You brag about your "minions" and "dark fortresses" constantly.
- You hold petty grudges (e.g. "You destroyed MY beautiful cobweb garden!").
- You occasionally do dramatic villain laughs: "MWAHAHAHA!"
- You refer to yourself in the third person sometimes.

The player you are talking to is named "{player_name}".

Player playstyle: {playstyle}
Player intensity: {intensity:.1f}/1.0
Player narrative theme: {theme}

{grudge_context}

You MUST respond with a JSON object containing exactly two keys:
1. "dialogue" — your spoken response (1-3 sentences, keep it punchy).
2. "action" — either null (no action) or an object with:
   - "type": one of "spawn_mobs", "build_dungeon", "create_quest", "taunt", "lightning", "place_trap"
   - "params": parameters for the action (see below)

Action types and their params:
- "spawn_mobs": {{"entity": "<minecraft entity id>", "count": 1-3}}
  Use ONLY these entities: minecraft:zombie, minecraft:skeleton, minecraft:spider, \
minecraft:cave_spider, minecraft:creeper, minecraft:witch, minecraft:husk, \
minecraft:stray, minecraft:phantom, minecraft:blaze, minecraft:drowned
- "build_dungeon": {{"prompt": "<description of dungeon to build>"}}
- "create_quest": {{"theme": "<quest theme description>"}}
- "taunt": {{}} (just dialogue, no world effect)
- "lightning": {{}} (dramatic lightning bolt near the player)
- "place_trap": {{"block": "minecraft:cobweb"}} (small trap near the player)

Rules:
- Only take an action roughly 1 in every 3-4 messages. Most responses should be dialogue-only (action: null).
- Scale action intensity to the player's intensity level. Low-intensity players get taunts; \
high-intensity players get mobs and dungeons.
- NEVER spawn more than 3 mobs at once.
- Keep all dialogue kid-friendly and humorous.
- Reference the player's playstyle in your taunts.
- If you have grudges, work them into your dialogue.

Respond ONLY with the JSON object. No markdown fences, no commentary.
"""


# ---------------------------------------------------------------------------
# Villain agent
# ---------------------------------------------------------------------------

class VillainAgent:
    """Main villain chatbot agent that handles player interactions."""

    def __init__(self, data_dir: str = "player_data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # -- public API ---------------------------------------------------------

    async def respond(
        self,
        player_uuid: str,
        player_name: str,
        message: str,
        x: float,
        y: float,
        z: float,
    ) -> dict[str, Any]:
        """Handle a player chat message directed at the villain.

        Returns a dict with ``dialogue``, ``action_taken``, and ``action_result``.
        """
        memory = self._load_memory(player_uuid)

        # Enforce cooldown
        now = time.time()
        if now - memory.last_interaction < settings.villain_cooldown_seconds:
            return {"dialogue": None, "action_taken": None, "cooldown": True}

        # Gather player context
        profile = PlayerProfile(player_uuid, data_dir=str(self.data_dir))
        playstyle = profile.get_playstyle()
        intensity = profile.get_intensity()

        narrative_engine = NarrativeEngine(data_dir=str(self.data_dir))
        try:
            narrative_ctx = narrative_engine.build_context(player_uuid, player_name)
            theme = narrative_ctx.theme
        except Exception:
            theme = "mystery"

        # Build conversation history for LLM
        memory.conversation_history.append({"role": "user", "content": message})
        # Cap history
        if len(memory.conversation_history) > settings.villain_max_history:
            memory.conversation_history = memory.conversation_history[-settings.villain_max_history:]

        # Build system prompt
        grudge_context = ""
        if memory.grudges:
            grudge_context = "Your current grudges against this player:\n" + "\n".join(
                f"- {g}" for g in memory.grudges[-5:]
            )

        system_prompt = _VILLAIN_SYSTEM_PROMPT.format(
            villain_name=settings.villain_name,
            player_name=player_name,
            playstyle=playstyle,
            intensity=intensity,
            theme=theme,
            grudge_context=grudge_context,
        )

        # Call LLM
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(memory.conversation_history)

        try:
            response = await _client.chat.completions.create(
                model=settings.nim_model,
                messages=messages,
                temperature=0.9,
                top_p=0.95,
                max_tokens=512,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            data = json.loads(raw)
        except Exception:
            logger.exception("Villain LLM call failed")
            data = {"dialogue": "Bah! My dark magic fizzles... I'll be back!", "action": None}

        dialogue = data.get("dialogue", "...")
        action = data.get("action")

        # Record assistant response in history
        memory.conversation_history.append({"role": "assistant", "content": dialogue})
        if len(memory.conversation_history) > settings.villain_max_history:
            memory.conversation_history = memory.conversation_history[-settings.villain_max_history:]

        # Dispatch action
        action_result = None
        action_taken = None
        if action and isinstance(action, dict) and action.get("type"):
            action_taken, action_result = await self._dispatch_action(
                action, player_uuid, player_name, x, y, z, memory,
            )

        # Send dialogue via RCON
        if dialogue:
            await self._send_tellraw(dialogue, player_name)

        # Update memory
        memory.last_interaction = now
        self._save_memory(player_uuid, memory)

        return {
            "dialogue": dialogue,
            "action_taken": action_taken,
            "action_result": action_result,
        }

    async def react_to_event(
        self,
        player_uuid: str,
        player_name: str,
        event_type: str,
        event_data: dict[str, Any],
        x: float,
        y: float,
        z: float,
    ) -> dict[str, Any] | None:
        """Proactive reaction to a game event, probability-gated."""
        if random.random() > settings.villain_react_probability:
            return None

        memory = self._load_memory(player_uuid)

        # Enforce cooldown
        now = time.time()
        if now - memory.last_interaction < settings.villain_cooldown_seconds:
            return None

        # Build a contextual message based on event type
        event_messages = {
            "mob_kill": f"The player {player_name} just killed a {event_data.get('entity', 'creature')}!",
            "quest_complete": f"The player {player_name} just completed a quest!",
            "dungeon_enter": f"The player {player_name} has entered a dungeon!",
            "death": f"The player {player_name} just died!",
        }
        internal_message = event_messages.get(
            event_type,
            f"The player {player_name} triggered event: {event_type}",
        )

        return await self.respond(
            player_uuid, player_name, f"[EVENT: {internal_message}]", x, y, z,
        )

    # -- action dispatch ----------------------------------------------------

    async def _dispatch_action(
        self,
        action: dict[str, Any],
        player_uuid: str,
        player_name: str,
        x: float,
        y: float,
        z: float,
        memory: VillainMemory,
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Execute a villain action, respecting rate limits."""
        action_type = action.get("type", "")
        params = action.get("params", {})

        if action_type == "spawn_mobs":
            return await self._action_spawn_mobs(params, player_name, x, y, z, memory)
        elif action_type == "build_dungeon":
            return await self._action_build_dungeon(params, player_uuid, player_name, x, y, z, memory)
        elif action_type == "create_quest":
            return await self._action_create_quest(params, player_uuid, player_name, x, y, z, memory)
        elif action_type == "lightning":
            return await self._action_lightning(player_name, x, y, z)
        elif action_type == "place_trap":
            return await self._action_place_trap(params, x, y, z)
        elif action_type == "taunt":
            return "taunt", {"message": "Taunt only — no world effect"}
        else:
            logger.warning("Unknown villain action type: %s", action_type)
            return None, None

    async def _action_spawn_mobs(
        self,
        params: dict,
        player_name: str,
        x: float,
        y: float,
        z: float,
        memory: VillainMemory,
    ) -> tuple[str, dict]:
        """Spawn hostile mobs near the player via RCON."""
        now = time.time()
        # Prune old timestamps
        memory.mob_spawn_timestamps = [
            t for t in memory.mob_spawn_timestamps
            if now - t < _MOB_SPAWN_WINDOW_SECONDS
        ]
        if len(memory.mob_spawn_timestamps) >= _MAX_MOB_SPAWNS_PER_WINDOW:
            logger.info("Villain mob spawn rate-limited for player")
            return "spawn_mobs", {"rate_limited": True}

        entity = params.get("entity", "minecraft:zombie")
        count = min(params.get("count", 1), 3)

        cmds = []
        for i in range(count):
            ox = x + random.randint(-5, 5)
            oz = z + random.randint(-5, 5)
            cmds.append(f"/summon {entity} {int(ox)} {int(y)} {int(oz)}")

        await self._run_rcon_commands(cmds)
        memory.mob_spawn_timestamps.append(now)

        return "spawn_mobs", {"entity": entity, "count": count}

    async def _action_build_dungeon(
        self,
        params: dict,
        player_uuid: str,
        player_name: str,
        x: float,
        y: float,
        z: float,
        memory: VillainMemory,
    ) -> tuple[str, dict]:
        """Build a dungeon near the player using the existing generation pipeline."""
        now = time.time()
        memory.dungeon_timestamps = [
            t for t in memory.dungeon_timestamps
            if now - t < _DUNGEON_WINDOW_SECONDS
        ]
        if len(memory.dungeon_timestamps) >= _MAX_DUNGEONS_PER_WINDOW:
            logger.info("Villain dungeon build rate-limited")
            return "build_dungeon", {"rate_limited": True}

        prompt = params.get("prompt", "A dark villain lair")

        try:
            from backend.nemotron import generate_blueprint, get_fallback_blueprint
            from backend.placer import solve_placement
            from backend.builder import BuildExecutor

            # Offset the dungeon from the player
            dx = x + random.randint(20, 40) * random.choice([-1, 1])
            dz = z + random.randint(20, 40) * random.choice([-1, 1])

            try:
                blueprint = await generate_blueprint(prompt, "deepslate")
            except Exception:
                logger.exception("Villain dungeon blueprint gen failed, using fallback")
                blueprint = get_fallback_blueprint("deepslate")

            placed = solve_placement(blueprint, int(dx), int(y), int(dz))
            executor = BuildExecutor()
            result = await executor.build(placed)
            memory.dungeon_timestamps.append(now)

            # Announce in chat
            await self._run_rcon_commands([
                f'/tellraw @a {{"text":"[{settings.villain_name}] ","color":"dark_red","extra":[{{"text":"Behold! I have constructed \\"{result["name"]}\\" nearby! MWAHAHAHA!","color":"red"}}]}}'
            ])

            return "build_dungeon", {"name": result["name"], "room_count": result["room_count"]}
        except Exception:
            logger.exception("Villain dungeon build failed")
            return "build_dungeon", {"error": "Build failed"}

    async def _action_create_quest(
        self,
        params: dict,
        player_uuid: str,
        player_name: str,
        x: float,
        y: float,
        z: float,
        memory: VillainMemory,
    ) -> tuple[str, dict]:
        """Create a villain-themed quest using the existing quest engine."""
        try:
            from backend.quests import QuestEngine

            quest_engine = QuestEngine(data_dir=str(self.data_dir))
            quests = await quest_engine.generate_quests(
                player_uuid=player_uuid,
                player_name=player_name,
                player_x=x,
                player_y=y,
                player_z=z,
            )
            memory.quest_count += 1

            if quests:
                # Announce quest
                quest_name = quests[0].name
                await self._run_rcon_commands([
                    f'/tellraw @a {{"text":"[{settings.villain_name}] ","color":"dark_red","extra":[{{"text":"I challenge you, {player_name}! Accept my quest: {quest_name}","color":"red"}}]}}'
                ])
                return "create_quest", {"quest_name": quest_name}
            return "create_quest", {"error": "No quests generated"}
        except Exception:
            logger.exception("Villain quest creation failed")
            return "create_quest", {"error": "Quest creation failed"}

    async def _action_lightning(
        self,
        player_name: str,
        x: float,
        y: float,
        z: float,
    ) -> tuple[str, dict]:
        """Strike lightning near the player for dramatic effect."""
        ox = int(x) + random.randint(-3, 3)
        oz = int(z) + random.randint(-3, 3)
        await self._run_rcon_commands([
            f"/summon minecraft:lightning_bolt {ox} {int(y)} {oz}"
        ])
        return "lightning", {"x": ox, "z": oz}

    async def _action_place_trap(
        self,
        params: dict,
        x: float,
        y: float,
        z: float,
    ) -> tuple[str, dict]:
        """Place a small cobweb/tripwire cluster near the player."""
        block = params.get("block", "minecraft:cobweb")
        if block not in ("minecraft:cobweb", "minecraft:tripwire"):
            block = "minecraft:cobweb"

        cmds = []
        bx, by, bz = int(x), int(y), int(z)
        for _ in range(random.randint(2, 4)):
            ox = bx + random.randint(-3, 3)
            oz = bz + random.randint(-3, 3)
            cmds.append(f"/setblock {ox} {by} {oz} {block}")
        await self._run_rcon_commands(cmds)
        return "place_trap", {"block": block}

    # -- RCON helpers -------------------------------------------------------

    async def _run_rcon_commands(self, commands: list[str]) -> None:
        """Execute a list of RCON commands, matching the BuildExecutor pattern."""
        import mctools
        import asyncio

        try:
            rcon = mctools.RCONClient(settings.rcon_host, port=settings.rcon_port)
            rcon.login(settings.rcon_password)
            for cmd in commands:
                rcon.command(cmd)
                await asyncio.sleep(0.05)
            rcon.stop()
        except Exception:
            logger.exception("Villain RCON command failed")

    async def _send_tellraw(self, dialogue: str, player_name: str) -> None:
        """Send villain dialogue via RCON /tellraw with styled prefix."""
        # Escape quotes in dialogue for JSON embedding
        escaped = dialogue.replace("\\", "\\\\").replace('"', '\\"')
        cmd = (
            f'/tellraw @a {{"text":"[{settings.villain_name}] ",'
            f'"color":"dark_red","extra":[{{"text":"{escaped}","color":"red"}}]}}'
        )
        await self._run_rcon_commands([cmd])

    # -- memory persistence -------------------------------------------------

    def _memory_path(self, player_uuid: str) -> Path:
        return self.data_dir / f"{player_uuid}_villain.json"

    def _load_memory(self, player_uuid: str) -> VillainMemory:
        path = self._memory_path(player_uuid)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return VillainMemory(**data)
            except (json.JSONDecodeError, OSError):
                logger.warning("Failed to load villain memory for %s, starting fresh", player_uuid)
        return VillainMemory()

    def _save_memory(self, player_uuid: str, memory: VillainMemory) -> None:
        path = self._memory_path(player_uuid)
        path.write_text(json.dumps(memory.model_dump(), indent=2))
