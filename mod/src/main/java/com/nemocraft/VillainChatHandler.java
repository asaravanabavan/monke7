package com.nemocraft;

import net.fabricmc.fabric.api.message.v1.ServerMessageEvents;
import net.minecraft.network.message.MessageType;
import net.minecraft.network.message.SignedMessage;
import net.minecraft.server.network.ServerPlayerEntity;

/**
 * Intercepts player chat messages and routes villain-targeted ones to the backend.
 *
 * Triggers when a player message contains "netherbane", "villain", or "@villain".
 * Also provides a static {@link #notifyEvent} method for other systems to fire
 * villain reactions (fire-and-forget).
 */
public class VillainChatHandler {

    private static volatile boolean villainEnabled = false;

    /** Register the chat listener. Called once from {@link NemoCraft#onInitialize()}. */
    public static void register() {
        ServerMessageEvents.CHAT_MESSAGE.register(VillainChatHandler::onChatMessage);
        NemoCraft.LOGGER.info("[NemoCraft] Villain chat handler registered");
    }

    /** Update the cached enabled flag (called from villain status check). */
    public static void setEnabled(boolean enabled) {
        villainEnabled = enabled;
    }

    /** Check if the villain is currently enabled. */
    public static boolean isEnabled() {
        return villainEnabled;
    }

    private static void onChatMessage(SignedMessage message, ServerPlayerEntity player, MessageType.Parameters params) {
        if (!villainEnabled) return;

        String content = message.getContent().getString().toLowerCase();

        // Only trigger on messages containing villain keywords
        if (!content.contains("netherbane") && !content.contains("villain") && !content.contains("@villain")) {
            return;
        }

        String uuid = player.getUuidAsString();
        String name = player.getName().getString();
        String rawMessage = message.getContent().getString();
        double x = player.getX();
        double y = player.getY();
        double z = player.getZ();

        // Fire-and-forget to backend, trigger portrait overlay on response
        BackendClient.villainChat(uuid, name, rawMessage, x, y, z)
                .thenAccept(response -> {
                    if (response.has("dialogue") && !response.get("dialogue").isJsonNull()) {
                        player.getServer().execute(() -> {
                            VillainNetworking.sendVillainSpeakPacket(player);
                        });
                    }
                })
                .exceptionally(error -> {
                    NemoCraft.LOGGER.debug("[NemoCraft] Villain chat failed: {}", error.getMessage());
                    return null;
                });
    }

    /**
     * Notify the villain of a game event (fire-and-forget).
     * Called from other systems like {@link QuestTracker}.
     *
     * @param player    the player involved in the event
     * @param eventType event type string (e.g. "mob_kill", "quest_complete")
     * @param eventData event context data (e.g. entity type killed)
     */
    public static void notifyEvent(ServerPlayerEntity player, String eventType, String eventData) {
        if (!villainEnabled) return;

        String uuid = player.getUuidAsString();
        String name = player.getName().getString();
        double x = player.getX();
        double y = player.getY();
        double z = player.getZ();

        BackendClient.villainEvent(uuid, name, eventType, eventData, x, y, z)
                .exceptionally(error -> {
                    NemoCraft.LOGGER.debug("[NemoCraft] Villain event failed: {}", error.getMessage());
                    return null;
                });
    }
}
