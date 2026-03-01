package com.nemocraft;

import net.minecraft.server.MinecraftServer;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.stat.ServerStatHandler;
import net.minecraft.stat.Stats;
import net.minecraft.entity.EntityType;
import net.minecraft.util.Identifier;
import net.minecraft.registry.Registries;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

public class PlayerStatsTracker {

    /**
     * Passive/neutral mob types whose kills affect karma negatively.
     * Maps EntityType -> stat key name sent to the backend.
     */
    private static final Map<EntityType<?>, String> PASSIVE_MOB_KEYS = new LinkedHashMap<>();
    static {
        PASSIVE_MOB_KEYS.put(EntityType.VILLAGER,    "killed_villager");
        PASSIVE_MOB_KEYS.put(EntityType.IRON_GOLEM,  "killed_iron_golem");
        PASSIVE_MOB_KEYS.put(EntityType.CAT,         "killed_cat");
        PASSIVE_MOB_KEYS.put(EntityType.WOLF,        "killed_wolf");
        PASSIVE_MOB_KEYS.put(EntityType.DOLPHIN,     "killed_dolphin");
        PASSIVE_MOB_KEYS.put(EntityType.HORSE,       "killed_horse");
        PASSIVE_MOB_KEYS.put(EntityType.DONKEY,      "killed_donkey");
        PASSIVE_MOB_KEYS.put(EntityType.TURTLE,      "killed_turtle");
        PASSIVE_MOB_KEYS.put(EntityType.BEE,         "killed_bee");
        PASSIVE_MOB_KEYS.put(EntityType.COW,         "killed_cow");
        PASSIVE_MOB_KEYS.put(EntityType.PIG,         "killed_pig");
        PASSIVE_MOB_KEYS.put(EntityType.SHEEP,       "killed_sheep");
        PASSIVE_MOB_KEYS.put(EntityType.FOX,         "killed_fox");
        PASSIVE_MOB_KEYS.put(EntityType.CHICKEN,     "killed_chicken");
        PASSIVE_MOB_KEYS.put(EntityType.RABBIT,      "killed_rabbit");
    }

    /**
     * Collect stats for a single player from MC's built-in stat tracking.
     * Includes both gameplay stats and karma-relevant counters.
     */
    public static Map<String, Object> collectStats(ServerPlayerEntity player) {
        ServerStatHandler statHandler = player.getStatHandler();
        Map<String, Object> stats = new HashMap<>();

        // Combat stats — sum kills across common hostile mob types
        int mobKills = 0;
        for (EntityType<?> entityType : new EntityType[]{
                EntityType.ZOMBIE, EntityType.SKELETON, EntityType.SPIDER,
                EntityType.CREEPER, EntityType.ENDERMAN, EntityType.WITCH,
                EntityType.CAVE_SPIDER, EntityType.BLAZE, EntityType.DROWNED,
                EntityType.HUSK, EntityType.STRAY, EntityType.PHANTOM,
                EntityType.PILLAGER, EntityType.VINDICATOR}) {
            mobKills += statHandler.getStat(Stats.KILLED, entityType);
        }
        stats.put("mob_kills", mobKills);

        stats.put("player_deaths", statHandler.getStat(Stats.CUSTOM, Stats.DEATHS));
        stats.put("damage_dealt", statHandler.getStat(Stats.CUSTOM, Stats.DAMAGE_DEALT));
        stats.put("damage_taken", statHandler.getStat(Stats.CUSTOM, Stats.DAMAGE_TAKEN));

        // Exploration stats — distance_traveled: sum of walk + sprint + swim + fly, converted from cm to blocks
        long distance = 0;
        distance += statHandler.getStat(Stats.CUSTOM, Stats.WALK_ONE_CM);
        distance += statHandler.getStat(Stats.CUSTOM, Stats.SPRINT_ONE_CM);
        distance += statHandler.getStat(Stats.CUSTOM, Stats.SWIM_ONE_CM);
        distance += statHandler.getStat(Stats.CUSTOM, Stats.FLY_ONE_CM);
        stats.put("distance_traveled", distance / 100.0);

        // --- Karma counters: passive/neutral mob kills ---
        for (Map.Entry<EntityType<?>, String> entry : PASSIVE_MOB_KEYS.entrySet()) {
            int killed = statHandler.getStat(Stats.KILLED, entry.getKey());
            stats.put(entry.getValue(), killed);
        }

        // --- Karma counters: positive actions ---
        // TRADED_WITH_VILLAGER
        stats.put("traded_with_villager",
                statHandler.getStat(Stats.CUSTOM, Stats.TRADED_WITH_VILLAGER));

        // TALKED_TO_VILLAGER
        stats.put("talked_to_villager",
                statHandler.getStat(Stats.CUSTOM, Stats.TALKED_TO_VILLAGER));

        // ANIMALS_BRED
        stats.put("animals_bred",
                statHandler.getStat(Stats.CUSTOM, Stats.ANIMALS_BRED));

        // FISH_CAUGHT
        stats.put("fish_caught",
                statHandler.getStat(Stats.CUSTOM, Stats.FISH_CAUGHT));

        // POT_FLOWER (flower potted)
        stats.put("pot_flower",
                statHandler.getStat(Stats.CUSTOM, Stats.POT_FLOWER));

        // RAID_WIN (raids won)
        stats.put("raid_win",
                statHandler.getStat(Stats.CUSTOM, Stats.RAID_WIN));

        // BELL_RING
        stats.put("bell_ring",
                statHandler.getStat(Stats.CUSTOM, Stats.BELL_RING));

        return stats;
    }

    /**
     * Send stats for all online players to the backend.
     */
    public static void sendAllPlayerStats(MinecraftServer server) {
        for (ServerPlayerEntity player : server.getPlayerManager().getPlayerList()) {
            try {
                Map<String, Object> stats = collectStats(player);
                String uuid = player.getUuidAsString();
                BackendClient.sendStats(uuid, stats)
                        .thenAccept(response -> {
                            NemoCraft.LOGGER.debug("[NemoCraft] Stats sent for {}", player.getName().getString());
                        })
                        .exceptionally(error -> {
                            NemoCraft.LOGGER.warn("[NemoCraft] Failed to send stats for {}: {}",
                                    player.getName().getString(), error.getMessage());
                            return null;
                        });
            } catch (Exception e) {
                NemoCraft.LOGGER.warn("[NemoCraft] Error collecting stats for {}: {}",
                        player.getName().getString(), e.getMessage());
            }
        }
    }
}
