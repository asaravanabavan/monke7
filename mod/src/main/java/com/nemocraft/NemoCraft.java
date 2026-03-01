package com.nemocraft;

import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.text.Text;
import net.minecraft.util.Formatting;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;

public class NemoCraft implements ModInitializer {
    public static final String MOD_ID = "nemocraft";
    public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

    private static final int STATS_INTERVAL_TICKS = 6000;   // 5 min at 20 TPS
    private static final int CHECK_INTERVAL_TICKS = 18000;   // 15 min at 20 TPS
    private static int tickCounter = 0;
    private static boolean villainStatusChecked = false;

    @Override
    public void onInitialize() {
        LOGGER.info("[NemoCraft] Initializing...");
        NemoBuildCommand.register();
        NemoQuestCommand.register();
        NemoVillainCommand.register();
        QuestTracker.registerEvents();
        VillainChatHandler.register();
        ServerTickEvents.END_SERVER_TICK.register(NemoCraft::onServerTick);
        LOGGER.info("[NemoCraft] Ready!");
    }

    private static void onServerTick(MinecraftServer server) {
        tickCounter++;

        // One-time villain status check on first tick
        if (!villainStatusChecked) {
            villainStatusChecked = true;
            BackendClient.villainStatus()
                    .thenAccept(response -> {
                        boolean enabled = response.has("enabled") && response.get("enabled").getAsBoolean();
                        VillainChatHandler.setEnabled(enabled);
                        LOGGER.info("[NemoCraft] Villain status: {}", enabled ? "enabled" : "disabled");
                    })
                    .exceptionally(error -> {
                        LOGGER.debug("[NemoCraft] Villain status check failed: {}", error.getMessage());
                        return null;
                    });
        }

        // Send stats every 5 minutes (with karma feedback)
        if (tickCounter % STATS_INTERVAL_TICKS == 0) {
            sendStatsWithKarmaFeedback(server);
        }

        // Check for auto-generation every 15 minutes
        if (tickCounter % CHECK_INTERVAL_TICKS == 0) {
            for (ServerPlayerEntity player : server.getPlayerManager().getPlayerList()) {
                String uuid = player.getUuidAsString();
                double x = player.getX();
                double y = player.getY();
                double z = player.getZ();
                BackendClient.checkAutoGenerate(uuid, x, y, z)
                        .thenAccept(response -> {
                            server.execute(() -> {
                                if (response.has("message")) {
                                    String msg = response.get("message").getAsString();
                                    boolean generated = response.has("generate") && response.get("generate").getAsBoolean();
                                    if (generated) {
                                        player.sendMessage(Text.literal("[NemoCraft] " + msg), false);
                                    }
                                }
                            });
                        })
                        .exceptionally(error -> {
                            LOGGER.debug("[NemoCraft] Auto-check failed: {}", error.getMessage());
                            return null;
                        });
            }
        }
    }

    /**
     * Send stats for all players and display karma feedback on their action bar.
     */
    private static void sendStatsWithKarmaFeedback(MinecraftServer server) {
        for (ServerPlayerEntity player : server.getPlayerManager().getPlayerList()) {
            try {
                Map<String, Object> stats = PlayerStatsTracker.collectStats(player);
                String uuid = player.getUuidAsString();
                BackendClient.sendStats(uuid, stats)
                        .thenAccept(response -> {
                            server.execute(() -> {
                                LOGGER.debug("[NemoCraft] Stats sent for {}", player.getName().getString());
                                // Display karma tier on action bar if non-neutral
                                if (response.has("karma_tier")) {
                                    String tier = response.get("karma_tier").getAsString();
                                    if (!"neutral".equals(tier)) {
                                        double score = response.has("karma_score")
                                                ? response.get("karma_score").getAsDouble() : 0;
                                        Formatting color = getKarmaColor(tier);
                                        String display = String.format("Karma: %s (%.0f)",
                                                tier.substring(0, 1).toUpperCase() + tier.substring(1),
                                                score);
                                        player.sendMessage(
                                                Text.literal(display).formatted(color),
                                                true  // action bar (non-intrusive)
                                        );
                                    }
                                }
                            });
                        })
                        .exceptionally(error -> {
                            LOGGER.warn("[NemoCraft] Failed to send stats for {}: {}",
                                    player.getName().getString(), error.getMessage());
                            return null;
                        });
            } catch (Exception e) {
                LOGGER.warn("[NemoCraft] Error collecting stats for {}: {}",
                        player.getName().getString(), e.getMessage());
            }
        }
    }

    /**
     * Map karma tier name to a Minecraft chat color.
     */
    private static Formatting getKarmaColor(String tier) {
        return switch (tier) {
            case "abyssal"  -> Formatting.DARK_RED;
            case "dark"     -> Formatting.RED;
            case "shadowed" -> Formatting.GRAY;
            case "blessed"  -> Formatting.YELLOW;
            case "sacred"   -> Formatting.AQUA;
            case "celestial"-> Formatting.LIGHT_PURPLE;
            default         -> Formatting.WHITE;
        };
    }
}
