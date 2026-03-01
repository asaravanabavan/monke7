# NemoCraft 🏰⚔️

NemoCraft is a dynamic, AI-powered dungeon generation system for Minecraft 1.20.1. By combining the vast architectural creativity of the **NVIDIA Llama-3-49B-Nemotron Base System** with procedural Minecraft rules, NemoCraft is capable of creating entirely unique, lore-accurate dungeons in real-time. 

Say goodbye to static, repetitive dungeon layouts. With a single prompt, you can summon sprawling catacombs, ruined temples, grand halls, and treacherous arenas directly into your Minecraft world.

---

## 🏗️ Features

* **True Generative Randomness:** AI dictates the theme, exact blocks used, overall footprint, item loot inside chests, and which enemy mobs spawn inside.
* **Procedural Architecture System:** The Python builder analyzes the AI's blueprint and fixes the geometry to make it structurally awesome. Instead of boring boxes, rooms are dynamically carved into L-shapes, T-shapes, and true Circles/Cylinders.
* **Smart Enhancements:** Rooms get automatically enhanced based on their volume:
  * *Grand Halls* get symmetrical pillar rows.
  * *Cathedrals* get stepped, vaulted ceilings and stained glass.
  * *Arenas* get sunken center pits with lava/water rings.
  * *Catacombs* get alcoves carved into walls and bone blocks scattered around.
  * *Fortresses* get external buttresses, iron-bar arrow slits, and battlements.
  * *Ruins* get mossy overgrowth, punched holes in walls, and crumbled ceilings.
* **Stats & Evolving Narrative (WIP/Phase 2):** Tracks your playstyle over time using exponential decay so that later dungeons dynamically adapt to how you play.

---

## ⚙️ Installation & Setup

This project requires two parts to be running simultaneously:
1. **The Java Fabric Mod** (running inside your Minecraft client/server).
2. **The Python Backend** (communicating with the AI and sending RCON commands to Minecraft).

### Prerequisites
* Java 17
* Python 3.10+
* Minecraft 1.20.1 with Fabric API
* An NVIDIA Developer API Key (for the NIM Nemotron inference)

### 1. Backend Setup

Open a terminal and navigate to the project root:

```bash
# 1. Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install properties
pip install -e ./backend
pip install "fastapi[standard]" pydantic pydantic-settings httpx mctools uvicorn

# 3. Configure the environment variables
cp .env.example .env
```

Open `.env` and paste your NVIDIA API key into `NEMO_NIM_API_KEY`. If needed, adjust the RCON port and password.

```bash
# Start the backend server
uvicorn backend.main:app --port 8000
```

### 2. Minecraft Server / Mod Setup

You need to enable RCON on your Minecraft server so the Python backend can remotely place the blocks.
Open your `server.properties` and ensure these lines are set:

```properties
enable-rcon=true
rcon.password=nemocraft
rcon.port=25575
```

If you are running the mod from source via Gradle:
```bash
cd mod
./gradlew build
./gradlew runServer
```

*(Alternatively, you can just drop the compiled `mod/build/libs/nemocraft-1.0.0.jar` into your normal Minecraft `mods` folder).*

---

## 🎮 How to Use

While in-game, ensure you have Operator (`/op`) status.

Point your crosshair at an empty area (or be floating in the air) and type:
```
/nemo build a grand nether fortress with lava moats and blaze spawners
```

* The mod will package your position and biome and send it to the Python backend.
* The backend will query Nemotron for a highly detailed blueprint (this takes 5-15 seconds depending on the size).
* You will see progress messages in chat (`[NemoCraft] Building room: "Blaze Spawner Sanctum" (1/3)`).
* The structure will be automatically built in chunks around you using RCON.

### Advanced Usage Examples:
* `/nemo build a sunken pirate cove`
* `/nemo build an elven treetop village`
* `/nemo build a ruined desert tomb full of husks`

---

## 🚀 Phase 2 (Coming Soon)
* **Karma System**: Track player good/evil actions (smelting nature vs planting bushes, healing vs killing villagers) resulting in Holy or Twisted thematic alignments for future dungeons.
* **Verticality**: True multi-story and multi-tiered dungeon layouts.
, 