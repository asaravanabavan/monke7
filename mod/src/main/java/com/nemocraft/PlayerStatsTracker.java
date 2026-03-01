package com.nemocraft;

import net.minecraft.server.MinecraftServer;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.stat.ServerStatHandler;
import net.minecraft.stat.Stats;
import net.minecraft.entity.EntityType;

import java.util.HashMap;
import java.util.Map;

public class PlayerStatsTracker {

    /**
     * Collect stats for a single player from MC's built-in stat tracking.
     * Only includes stats that can be reliably read from vanilla MC 1.20.1.
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
