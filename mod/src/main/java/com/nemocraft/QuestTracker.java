package com.nemocraft;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import net.fabricmc.fabric.api.entity.event.v1.ServerLivingEntityEvents;
import net.minecraft.entity.LivingEntity;
import net.minecraft.entity.damage.DamageSource;
import net.minecraft.entity.mob.HostileEntity;
import net.minecraft.registry.Registries;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.text.Text;
import net.minecraft.util.Formatting;
import net.minecraft.util.Identifier;

/**
 * Tracks in-game events and automatically reports quest progress to the backend.
 *
 * Currently tracks:
 * - Mob kills: when a player kills a hostile mob, sends a "kill" progress update
 *
 * Quest completions are announced in chat when all objectives are met.
 */
public class QuestTracker {

    /**
     * Register all event listeners for quest progress tracking.
     * Called once from {@link NemoCraft#onInitialize()}.
     */
    public static void registerEvents() {
        // Track mob kills
        ServerLivingEntityEvents.AFTER_DEATH.register(QuestTracker::onEntityDeath);
        NemoCraft.LOGGER.info("[NemoCraft] Quest tracker registered");
    }

    private static void onEntityDeath(LivingEntity entity, DamageSource source) {
        // Only care about hostile mob kills by a player
        if (!(entity instanceof HostileEntity)) return;
        if (!(source.getAttacker() instanceof ServerPlayerEntity player)) return;

        // Get the entity type ID (e.g. "minecraft:zombie")
        Identifier entityId = Registries.ENTITY_TYPE.getId(entity.getType());
        String target = entityId.toString();
        String uuid = player.getUuidAsString();

        // Send kill progress to backend
        BackendClient.sendQuestProgress(uuid, "kill", target, 1)
                .thenAccept(response -> {
                    player.getServer().execute(() -> {
                        // Check if any quests were completed by this kill
                        if (response.has("completed_quests")) {
                            JsonArray completed = response.getAsJsonArray("completed_quests");
                            for (JsonElement elem : completed) {
                                JsonObject quest = elem.getAsJsonObject();
                                String questName = quest.has("name") ? quest.get("name").getAsString() : "a quest";
                                String questId = quest.has("quest_id") ? quest.get("quest_id").getAsString() : "";

                                player.sendMessage(Text.literal("").formatted(Formatting.GOLD)
                                        .append(Text.literal("[NemoCraft] ").formatted(Formatting.GOLD))
                                        .append(Text.literal("Quest complete: ").formatted(Formatting.GREEN))
                                        .append(Text.literal(questName).formatted(Formatting.GOLD, Formatting.BOLD))
                                        .append(Text.literal("!").formatted(Formatting.GREEN)), false);
                                player.sendMessage(Text.literal("  Use ").formatted(Formatting.GRAY)
                                        .append(Text.literal("/nemo quest complete " + questId).formatted(Formatting.YELLOW))
                                        .append(Text.literal(" to claim your reward!").formatted(Formatting.GRAY)), false);
                            }
                        }
                    });
                })
                .exceptionally(error -> {
                    // Silently ignore — quest progress is best-effort
                    NemoCraft.LOGGER.debug("[NemoCraft] Quest progress send failed: {}", error.getMessage());
                    return null;
                });
    }
}
