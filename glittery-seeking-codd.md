# NemoCraft Hackathon MVP — Implementation Plan

## Context

Build a hackathon MVP of NemoCraft: type `/nemo build <prompt>` in Minecraft chat, an AI generates a dungeon blueprint, and the structure appears in the world via RCON commands. Two components: a Fabric mod (Java, MC 1.20.4) and a Python backend (FastAPI + Nemotron API).

## Architecture

```
Player types /nemo build <prompt>
        │
        ▼
Fabric Mod (Java) ──HTTP POST──► Python Backend (FastAPI :8000)
  • registers command                │
  • sends player pos/biome          ▼
  • shows result in chat       Nemotron API (NVIDIA NIM)
                                    │ JSON blueprint
                                    ▼
                              Pydantic Validation
                                    │
                                    ▼
                              Room Placement Solver
                                    │ absolute coords
                                    ▼
                              RCON Build Executor ──► Minecraft Server
                                /fill, /summon,        (builds structure)
                                /setblock, /tellraw
```

## Project Structure

```
~/Projects/nemocraft/
├── mod/                               # Fabric mod (Java)
│   ├── build.gradle, settings.gradle, gradle.properties
│   ├── gradle/wrapper/
│   └── src/main/
│       ├── java/com/nemocraft/
│       │   ├── NemoCraft.java         # ModInitializer → registers command
│       │   ├── NemoBuildCommand.java   # /nemo build <prompt> → async HTTP call
│       │   └── BackendClient.java     # java.net.http.HttpClient → POST /api/build
│       └── resources/
│           └── fabric.mod.json
└── backend/                           # Python backend
    ├── pyproject.toml
    ├── main.py                        # FastAPI app: /api/build endpoint + fallback template
    ├── nemotron.py                    # OpenAI-compatible client → NVIDIA NIM API
    ├── blueprint.py                   # Pydantic models: Blueprint, Room, Corridor, MobSpawn, LootChest
    ├── placer.py                      # Linear chain placement solver (rooms along +Z axis)
    ├── builder.py                     # RCON executor: fill → shell → detail → mobs → loot
    ├── registries.py                  # Hardcoded sets of valid block/entity/item IDs
    └── config.py                      # pydantic-settings: env vars with NEMO_ prefix
```

## Implementation Steps

### Step 1: Project scaffolding
- Create `mod/build.gradle` with Fabric Loom 1.5, MC 1.20.4, Yarn mappings, Fabric API 0.96.11
- Create `mod/settings.gradle` with Fabric Maven repo
- Create `mod/gradle.properties` with version pins
- Generate Gradle wrapper targeting Gradle 8.5 (Loom 1.5 compatibility)
- Create `backend/pyproject.toml` with deps: fastapi, uvicorn, pydantic, pydantic-settings, openai, mctools, httpx
- Init git repo

### Step 2: Backend — registries.py
- Hardcoded `VALID_BLOCK_IDS`, `VALID_ENTITY_IDS`, `VALID_ITEM_IDS` sets
- Covers 3 palettes: stone dungeon, nether fortress, ocean monument
- ~60 block IDs, ~15 entity IDs, ~30 item IDs (curated subset, not full registry)

### Step 3: Backend — blueprint.py (Pydantic models)
- `Blueprint` → `name`, `palette`, `rooms[]`, `corridors[]`
- `Room` → `name`, `description`, dimensions (5-25 x 4-15 x 5-25), shell/floor/ceiling blocks, `details[]`, `mobs[]`, `loot_chests[]`
- `BlockPlacement` → relative coords within room + block_id + mode
- `MobSpawn` → entity_id + relative coords + count (1-5)
- `LootChest` → relative coords + facing + items[] (max 27 slots)
- `Corridor` → length/width/height + wall block
- Validators: block/entity/item IDs against registries, detail coords within room bounds, corridor count = rooms - 1, total volume check

### Step 4: Backend — config.py
- `pydantic-settings` with `NEMO_` env prefix
- Settings: NIM API key/URL/model, RCON host/port/password, backend host/port, build delay, max rooms

### Step 5: Backend — nemotron.py
- Use `openai.AsyncOpenAI` pointed at `https://integrate.api.nvidia.com/v1` (NIM is OpenAI-compatible)
- System prompt embeds the Pydantic JSON schema so model knows exact structure to produce
- User prompt includes: player's text prompt, palette, num_rooms, biome, player coords
- `response_format={"type": "json_object"}` to constrain output
- Parse response with `Blueprint.model_validate_json()`
- On failure: caller falls back to hardcoded template

### Step 6: Backend — placer.py
- Linear chain along +Z axis: Room₀ → Corridor₀ → Room₁ → Corridor₁ → Room₂
- Each room X-centered on player's X coordinate
- Advance `current_z` by room depth, then corridor length
- Output: `PlacedBlueprint` with absolute world coordinates for each room/corridor

### Step 7: Backend — builder.py (RCON executor)
- `BuildExecutor` class with RCON connection management
- Build phases per room: shell (hollow fill) → floor → ceiling → details → mobs → loot chests
- Corridor phases: shell → carve interior → open ends
- Doorway punching: open walls between rooms and corridors
- `/fill` chunking for volumes > 32768 blocks
- Chest items via `/setblock` + `/data merge` with NBT
- Mobs via `/summon`
- Progress messages via `/tellraw @a`
- `asyncio.sleep` between rooms to avoid server lag

### Step 8: Backend — main.py (FastAPI app)
- `POST /api/build` endpoint: accepts `BuildRequest` (prompt, player_name, x/y/z, biome, palette)
- Pipeline: generate_blueprint → solve_placement → builder.build
- Auto-detect palette from prompt keywords (nether/ocean/etc)
- Fallback: hardcoded single-room dungeon if Nemotron fails
- `GET /health` endpoint
- Structure placed 5 blocks north of player

### Step 9: Fabric mod — fabric.mod.json
- Schema version 1, mod ID "nemocraft"
- Entrypoint: `com.nemocraft.NemoCraft`
- Depends on fabricloader >=0.15.0, minecraft ~1.20.4, java >=17

### Step 10: Fabric mod — NemoCraft.java
- Implements `ModInitializer`
- `onInitialize()` calls `NemoBuildCommand.register()`

### Step 11: Fabric mod — BackendClient.java
- Uses `java.net.http.HttpClient` (built into JDK, no extra deps)
- Uses Gson (bundled by Minecraft) for JSON
- `requestBuild()` returns `CompletableFuture<BuildResponse>`
- 120-second timeout (LLM generation can be slow)

### Step 12: Fabric mod — NemoBuildCommand.java
- Registers `/nemo build <prompt>` via Brigadier + `CommandRegistrationCallback`
- `StringArgumentType.greedyString()` captures full prompt
- Gets player position + biome name
- Sends immediate "Generating..." feedback
- Dispatches async HTTP call to backend
- On success/failure: routes response back to server thread via `source.getServer().execute()`

### Step 13: Integration testing
- Build mod JAR with `./gradlew build`
- Install dependencies with `uv sync` or `pip install -e .`
- Configure MC server: `enable-rcon=true`, `rcon.port=25575`, `rcon.password=nemocraft`
- Set `NEMO_NIM_API_KEY` env var
- Start backend: `cd backend && uvicorn backend.main:app --port 8000`
- Start MC server with mod, join, test `/nemo build`

## Key Design Decisions

1. **HTTP instead of WebSocket** — simpler for on-demand mode; progress comes via RCON `/tellraw` directly
2. **OpenAI client for NIM** — NVIDIA NIM is OpenAI-compatible, avoid custom HTTP logic
3. **Linear room chain** — rooms placed in a line along +Z, no complex branching/graph solving
4. **Pydantic schema in prompt** — embed `Blueprint.model_json_schema()` in system prompt so model knows exact structure
5. **Fallback template** — hardcoded single-room dungeon ensures demo always works even if API is down
6. **No external Java deps** — use JDK HttpClient + Minecraft's bundled Gson
7. **Java 17 target** — MC 1.20.4 requires Java 17 bytecode (Java 21 JDK compiles it fine)

## Verification

1. `curl http://localhost:8000/health` → `{"status":"ok"}`
2. `curl -X POST http://localhost:8000/api/build -H 'Content-Type: application/json' -d '{"prompt":"test dungeon","player_name":"Test","x":0,"y":64,"z":0}'` → verify JSON response
3. In Minecraft: `/nemo build a dark stone dungeon with zombie spawners` → structure appears
4. Check server logs for `[NemoCraft] Ready!` on mod load
5. Verify RCON: send test `/say hello` via mctools CLI
