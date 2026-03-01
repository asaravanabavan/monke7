# NemoCraft Hackathon MVP — Implementation Plan

## Context

Build a Minecraft dungeon generator: `/nemo build <prompt>` in chat triggers an AI to generate a dungeon blueprint, which gets built in the world via RCON. Two components: Fabric mod (Java, **MC 1.20.1**) + Python backend (FastAPI + NVIDIA Nemotron). Everything built inside `/home/hamed/projects/ucl_ai_engine/`. User will set up the MC server separately later.

## Project Structure

```
/home/hamed/projects/ucl_ai_engine/
├── mod/                               # Fabric mod (Java)
│   ├── build.gradle, settings.gradle, gradle.properties
│   ├── gradle/wrapper/
│   └── src/main/
│       ├── java/com/nemocraft/
│       │   ├── NemoCraft.java         # ModInitializer + periodic scheduler
│       │   ├── NemoBuildCommand.java   # /nemo build <prompt> (manual trigger)
│       │   ├── BackendClient.java     # HTTP client → POST /api/build + /api/check
│       │   └── PlayerStatsTracker.java # Reads MC scoreboard stats, sends to backend
│       └── resources/fabric.mod.json
├── backend/                           # Python backend
│   ├── pyproject.toml
│   ├── __init__.py                    # Package init (required for pip install -e)
│   ├── main.py                        # FastAPI app (endpoints: /build, /check, /health)
│   ├── nemotron.py                    # OpenAI client → NVIDIA NIM
│   ├── blueprint.py                   # Pydantic models
│   ├── placer.py                      # Room placement solver
│   ├── builder.py                     # RCON executor
│   ├── registries.py                  # Valid block/entity/item IDs
│   ├── config.py                      # pydantic-settings (NEMO_ prefix)
│   ├── stats.py                       # Player stats with exponential decay
│   └── narrative.py                   # Evolving narrative engine (player profile → story context)
├── .env                               # Environment variables (NEMO_NIM_API_KEY, RCON settings)
└── .venv/                             # Existing venv (use this, no global installs)
```

## Required Keys

- **`NEMO_NIM_API_KEY`** — NVIDIA NIM API key (user has this)
- **RCON password** — set in MC server's `server.properties` (default: `nemocraft`)

## Sub-Agent Parallelization Strategy

To maximize coding efficiency, work is split into parallel agent batches:

### Batch 0: Scaffolding (sequential — must complete first)
- **Main thread**: Create directory structure, build files, pyproject.toml, install deps into `.venv`

### Batch 1: Three agents in parallel (no cross-dependencies)
| Agent | Files | Steps |
|-------|-------|-------|
| **Agent A: Backend Foundation** | `registries.py`, `blueprint.py`, `config.py` | 2, 3, 4 |
| **Agent B: Mod Core** | `fabric.mod.json`, `NemoCraft.java`, `BackendClient.java`, `NemoBuildCommand.java` | 9, 10, 11, 12 |
| **Agent C: Backend Placement + Stats** | `placer.py`, `stats.py` | 6, 13 |

### Batch 2: Three agents in parallel (depend on Batch 1)
| Agent | Files | Depends on | Steps |
|-------|-------|------------|-------|
| **Agent D: Nemotron Client** | `nemotron.py` | blueprint.py, config.py (Agent A) | 5 |
| **Agent E: RCON Builder** | `builder.py` | blueprint.py, config.py, placer.py (Agents A+C) | 7 |
| **Agent F: Narrative Engine** | `narrative.py` | stats.py (Agent C), config.py (Agent A) | 14 |

### Batch 3: Two agents in parallel
| Agent | Files | Depends on | Steps |
|-------|-------|------------|-------|
| **Agent G: FastAPI App** | `main.py` | All backend modules | 8, 16 (endpoints) |
| **Agent H: Mod Stats + Periodic** | `PlayerStatsTracker.java`, update `NemoCraft.java` | BackendClient (Agent B) | 15, 16 (mod side) |

### Batch 4: Integration testing (sequential)
- **Main thread**: Full system testing | Step 17 |

**Dependency graph:**
```
Scaffolding (Step 1)
    ├──► Agent A (registries + blueprint + config)
    │        ├──► Agent D (nemotron) ──────────►┐
    │        ├──► Agent E (builder) ────────────►├─► Agent G (main.py) → Testing
    │        └──► Agent F (narrative) ──────────►┘        ▲
    ├──► Agent B (mod core files) ──────────────► Agent H (stats tracker) ─┘
    └──► Agent C (placer + stats) ──────────────►┘
```

## Implementation Steps

### Step 1: Project Scaffolding
- Create `mod/` directory with `build.gradle` (Fabric Loom 1.5, **MC 1.20.1**, Yarn mappings `1.20.1+build.10`, Fabric API `0.92.2+1.20.1`)
- Create `mod/settings.gradle` with Fabric Maven repo
- Create `mod/gradle.properties` with version pins for 1.20.1
- Download Gradle wrapper files (gradle-wrapper.jar + gradle-wrapper.properties) targeting Gradle 8.5
- Create `backend/pyproject.toml` with deps: fastapi, uvicorn, pydantic, pydantic-settings, openai, mctools, httpx
- Create `backend/__init__.py` (empty, needed for package)
- Create `.env` template with placeholder values for `NEMO_NIM_API_KEY`, RCON host/port/password
- Install backend deps into existing `.venv` (`source .venv/bin/activate && pip install -e ./backend`)

### Step 2: Backend — registries.py
- Hardcoded `VALID_BLOCK_IDS`, `VALID_ENTITY_IDS`, `VALID_ITEM_IDS` sets
- ~60 blocks, ~15 entities, ~30 items covering stone dungeon, nether fortress, ocean monument palettes

### Step 3: Backend — blueprint.py (Pydantic models)
- `Blueprint` → name, palette, rooms[], corridors[]
- `Room` → name, dimensions (5-25 x 4-15 x 5-25), shell/floor/ceiling blocks, details[], mobs[], loot_chests[]
- `BlockPlacement`, `MobSpawn`, `LootChest`, `Corridor` models
- Validators: IDs against registries, coords within bounds, corridor count = rooms - 1

### Step 4: Backend — config.py
- `pydantic-settings` with `NEMO_` env prefix
- Settings: NIM API key/URL/model, RCON host/port/password, backend host/port, build delay, max rooms

### Step 5: Backend — nemotron.py
- `openai.AsyncOpenAI` pointed at `https://integrate.api.nvidia.com/v1`
- System prompt embeds Pydantic JSON schema
- `response_format={"type": "json_object"}` to constrain output
- Parse response with `Blueprint.model_validate_json()`
- On failure: caller falls back to hardcoded template

### Step 6: Backend — placer.py
- Linear chain along +Z: Room₀ → Corridor₀ → Room₁ → ...
- Rooms X-centered on player X, advancing `current_z` by room depth + corridor length
- Output: `PlacedBlueprint` with absolute world coordinates

### Step 7: Backend — builder.py (RCON executor)
- `BuildExecutor` with RCON connection management
- Build phases per room: shell → floor → ceiling → details → mobs → loot chests
- Corridor phases: shell → carve interior → open ends
- `/fill` chunking for volumes > 32768 blocks
- Chest items via `/setblock` + `/data merge` with NBT
- Mobs via `/summon`, progress via `/tellraw @a`
- `asyncio.sleep` between rooms to avoid server lag

### Step 8: Backend — main.py (FastAPI app)
- `POST /api/build` endpoint: BuildRequest (prompt, player_name, x/y/z, biome, palette)
- Pipeline: generate_blueprint → solve_placement → builder.build
- Auto-detect palette from prompt keywords
- Fallback: hardcoded single-room dungeon if Nemotron fails
- `GET /health` endpoint

### Step 9: Fabric mod — fabric.mod.json
- Schema version 1, mod ID "nemocraft", entrypoint `com.nemocraft.NemoCraft`
- Depends: fabricloader >=0.15.0, minecraft ~1.20.1, java >=17

### Step 10: Fabric mod — NemoCraft.java
- `ModInitializer`, `onInitialize()` calls `NemoBuildCommand.register()`

### Step 11: Fabric mod — BackendClient.java
- `java.net.http.HttpClient` + Gson (bundled by MC)
- `requestBuild()` returns `CompletableFuture<BuildResponse>`, 120s timeout

### Step 12: Fabric mod — NemoBuildCommand.java
- Registers `/nemo build <prompt>` via Brigadier + `CommandRegistrationCallback`
- `StringArgumentType.greedyString()` for full prompt
- Gets player position + biome
- Async HTTP call, response routed back to server thread

### Step 13: Backend — stats.py (Player Stats with Decay)
- `PlayerStats` Pydantic model: tracks broad gameplay stats
  - Combat: mob_kills (by type), player_deaths, damage_dealt, damage_taken
  - Exploration: biomes_visited, distance_traveled, unique_structures_found
  - Building: blocks_placed, blocks_broken (by type)
  - Crafting: items_crafted, items_used
- **Exponential decay function**: `decayed_value = raw_value * e^(-λ * hours_elapsed)`
  - λ (decay rate) configurable per stat category (combat decays faster than exploration)
  - Default: combat λ=0.05 (~14h half-life), exploration λ=0.02 (~35h half-life)
  - Decay calculated at query time, not stored
- `PlayerProfile` class:
  - Stores raw stat snapshots with timestamps
  - `get_decayed_stats()` → returns current effective stats after decay
  - `get_playstyle()` → categorizes player: "aggressive", "explorer", "builder", "balanced"
  - `get_intensity()` → 0.0-1.0 score of how active the player has been recently
- Persistence: `player_stats.json` file per player

### Step 14: Backend — narrative.py (Evolving Narrative Engine)
- `NarrativeEngine` class:
  - Maintains a running story context per player
  - Uses decayed stats to determine narrative themes:
    - High villager kills → "The land cries for justice" → retribution-themed dungeons
    - High exploration → "A forgotten realm reveals itself" → discovery-themed dungeons
    - High building → "Your creations attract attention" → invasion-themed dungeons
  - Difficulty scaling: `base_difficulty + (intensity * difficulty_multiplier)`
    - More recent activity = harder dungeons, decayed activity = easier
  - Generates a `NarrativeContext` passed to Nemotron:
    - `theme`, `mood`, `difficulty_level` (1-10), `story_hook`, `loot_quality`, `mob_count_multiplier`
  - Story continuity: references previous dungeons in narrative prompts
- Persistence: `narrative_history.json` per player

### Step 15: Mod — PlayerStatsTracker.java
- Reads MC scoreboard stats via `ServerScoreboard` API
  - MC natively tracks: `minecraft.killed:*`, `minecraft.mined:*`, `minecraft.crafted:*`, etc.
- Collects stats snapshot every N minutes (configurable, default 5 min)
- Sends stats to backend via `POST /api/stats` with player UUID + stat map
- Lightweight: only reads existing scoreboard criteria, no custom events needed

### Step 16: Periodic Auto-Generation
- Mod side: `NemoCraft.java` registers a tick-based scheduler
  - Every `check_interval` minutes (default 15), calls `POST /api/check`
  - Sends player UUID + current position
- Backend side: `POST /api/check` endpoint in `main.py`
  - Loads player's decayed stats → calculates intensity
  - If intensity > threshold (configurable, default 0.3): trigger generation
  - Uses `NarrativeEngine` to build context → passes to Nemotron → builds dungeon
  - Cooldown: minimum 30 minutes between auto-generations per player
  - Returns `{"generate": true/false, "message": "..."}` to mod for `/tellraw` feedback

### Step 17: Integration Testing (Full System)
- Build mod JAR: `cd mod && ./gradlew build`
- Install backend: `source .venv/bin/activate && pip install -e ./backend`
- Configure MC server: `enable-rcon=true`, `rcon.port=25575`, `rcon.password=nemocraft`
- Set `NEMO_NIM_API_KEY` env var
- Start backend: `source .venv/bin/activate && cd backend && uvicorn backend.main:app --port 8000`
- Test: `curl http://localhost:8000/health`

## Important Notes
- All Python operations use the existing `.venv` — no global pip installs
- NVIDIA NIM is OpenAI-compatible, so we use the `openai` Python client
- Java mod uses only JDK built-ins + MC-bundled Gson (no extra deps)
- Fallback template ensures demo works even without API key

## Verification
1. `curl http://localhost:8000/health` → `{"status":"ok"}`
2. `curl -X POST http://localhost:8000/api/build -H 'Content-Type: application/json' -d '{"prompt":"test dungeon","player_name":"Test","x":0,"y":64,"z":0}'` → JSON response
3. In Minecraft: `/nemo build a dark stone dungeon with zombie spawners` → structure appears
4. Check server logs for `[NemoCraft] Ready!` on mod load

## Phase 2 (To-Do)
### 1. Finetuning Structure Generation (True Randomness)
- Further expand architectural layout algorithms (avoiding standard boxes).
- Implement multi-story / multi-tier room generation (verticality).
- Add structural rotation and organic winding paths that adapt to terrain logic.
- Make the AI blueprints even more unconstrained while the python builder ensures structural integrity via diverse procedural building strategies.

### 2. Karma System Implementation
- Track player actions (e.g., helping vs harming villagers, replanting vs destroying nature) alongside general stats.
- Modify the narrative engine to account for a "Karma Score" ranging from -100 (Evil) to +100 (Pure).
- Dungeons generated for "Evil" players become themed around dark magic, punishment, and twisted structures.
- Dungeons generated for "Pure" players become themed around light, tests of virtue, and ancient guardian temples.
- Update `/api/stats` to calculate and decay Karma independently of intensity.
