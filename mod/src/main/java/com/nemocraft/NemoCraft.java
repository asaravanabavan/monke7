package com.nemocraft;

import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.text.Text;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class NemoCraft implements ModInitializer {
    public static final String MOD_ID = "nemocraft";
    public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

    private static final int STATS_INTERVAL_TICKS = 6000;   // 5 min at 20 TPS
    private static final int CHECK_INTERVAL_TICKS = 18000;   // 15 min at 20 TPS
    private static int tickCounter = 0;

    @Override
    public void onInitialize() {
        LOGGER.info("[NemoCraft] Initializing...");
        NemoBuildCommand.register();
        NemoQuestCommand.register();
        QuestTracker.registerEvents();
        ServerTickEvents.END_SERVER_TICK.register(NemoCraft::onServerTick);
        LOGGER.info("[NemoCraft] Ready!");
    }

    private static void onServerTick(MinecraftServer server) {
        tickCounter++;

        // Send stats every 5 minutes
        if (tickCounter % STATS_INTERVAL_TICKS == 0) {
            PlayerStatsTracker.sendAllPlayerStats(server);
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
}
