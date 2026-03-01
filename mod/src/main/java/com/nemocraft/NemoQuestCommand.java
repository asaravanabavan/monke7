package com.nemocraft;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.context.CommandContext;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.server.command.CommandManager;
import net.minecraft.server.command.ServerCommandSource;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.text.MutableText;
import net.minecraft.text.Text;
import net.minecraft.util.Formatting;

/**
 * Registers quest-related subcommands under /nemo:
 *
 *   /nemo quest          — Generate new quests for the player
 *   /nemo quests         — List current active quests
 *   /nemo quest accept <id> — Accept a quest
 *   /nemo quest complete <id> — Complete a quest and build its destination
 */
public class NemoQuestCommand {

    public static void register() {
        CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> {
            dispatcher.register(
                CommandManager.literal("nemo")
                    // /nemo quest — generate new quests
                    .then(CommandManager.literal("quest")
                        .executes(NemoQuestCommand::executeGenerate)
                        // /nemo quest accept <id>
                        .then(CommandManager.literal("accept")
                            .then(CommandManager.argument("quest_id", StringArgumentType.word())
                                .executes(NemoQuestCommand::executeAccept)
                            )
                        )
                        // /nemo quest complete <id>
                        .then(CommandManager.literal("complete")
                            .then(CommandManager.argument("quest_id", StringArgumentType.word())
                                .executes(NemoQuestCommand::executeComplete)
                            )
                        )
                    )
                    // /nemo quests — list active quests
                    .then(CommandManager.literal("quests")
                        .executes(NemoQuestCommand::executeList)
                    )
            );
        });
        NemoCraft.LOGGER.info("[NemoCraft] Quest commands registered");
    }

    // -- /nemo quest (generate) -------------------------------------------

    private static int executeGenerate(CommandContext<ServerCommandSource> context) {
        ServerCommandSource source = context.getSource();
        if (!(source.getEntity() instanceof ServerPlayerEntity player)) {
            source.sendFeedback(() -> Text.literal("[NemoCraft] Must be run by a player."), false);
            return 0;
        }

        String uuid = player.getUuidAsString();
        String name = player.getName().getString();
        double x = player.getX();
        double y = player.getY();
        double z = player.getZ();

        source.sendFeedback(() -> Text.literal("[NemoCraft] ").formatted(Formatting.GOLD)
                .append(Text.literal("Generating quests...").formatted(Formatting.YELLOW)), false);

        BackendClient.generateQuests(uuid, name, x, y, z)
                .thenAccept(response -> {
                    source.getServer().execute(() -> {
                        if (response.has("quests")) {
                            JsonArray quests = response.getAsJsonArray("quests");
                            if (quests.size() == 0) {
                                source.sendFeedback(() -> Text.literal("[NemoCraft] ").formatted(Formatting.GOLD)
                                        .append(Text.literal("No new quests available. You already have the maximum active quests, or try again later.").formatted(Formatting.GRAY)), false);
                                return;
                            }
                            source.sendFeedback(() -> Text.literal("[NemoCraft] ").formatted(Formatting.GOLD)
                                    .append(Text.literal("New quests available!").formatted(Formatting.GREEN)), false);
                            for (JsonElement elem : quests) {
                                JsonObject q = elem.getAsJsonObject();
                                displayQuestSummary(source, q);
                            }
                            source.sendFeedback(() -> Text.literal("Use ").formatted(Formatting.GRAY)
                                    .append(Text.literal("/nemo quest accept <id>").formatted(Formatting.YELLOW))
                                    .append(Text.literal(" to accept a quest.").formatted(Formatting.GRAY)), false);
                        } else {
                            String msg = response.has("message") ? response.get("message").getAsString() : "Unknown error";
                            source.sendFeedback(() -> Text.literal("[NemoCraft] " + msg).formatted(Formatting.RED), false);
                        }
                    });
                })
                .exceptionally(error -> {
                    source.getServer().execute(() -> {
                        source.sendFeedback(() -> Text.literal("[NemoCraft] Failed to generate quests: " + error.getMessage()).formatted(Formatting.RED), false);
                    });
                    return null;
                });

        return 1;
    }

    // -- /nemo quests (list) -----------------------------------------------

    private static int executeList(CommandContext<ServerCommandSource> context) {
        ServerCommandSource source = context.getSource();
        if (!(source.getEntity() instanceof ServerPlayerEntity player)) {
            source.sendFeedback(() -> Text.literal("[NemoCraft] Must be run by a player."), false);
            return 0;
        }

        String uuid = player.getUuidAsString();

        BackendClient.listQuests(uuid)
                .thenAccept(response -> {
                    source.getServer().execute(() -> {
                        JsonArray quests = response.has("quests") ? response.getAsJsonArray("quests") : new JsonArray();
                        if (quests.size() == 0) {
                            source.sendFeedback(() -> Text.literal("[NemoCraft] ").formatted(Formatting.GOLD)
                                    .append(Text.literal("No active quests. Use ").formatted(Formatting.GRAY))
                                    .append(Text.literal("/nemo quest").formatted(Formatting.YELLOW))
                                    .append(Text.literal(" to generate new ones!").formatted(Formatting.GRAY)), false);
                            return;
                        }
                        source.sendFeedback(() -> Text.literal("=== Your Quests ===").formatted(Formatting.GOLD, Formatting.BOLD), false);
                        for (JsonElement elem : quests) {
                            JsonObject q = elem.getAsJsonObject();
                            displayQuestDetail(source, q);
                        }
                    });
                })
                .exceptionally(error -> {
                    source.getServer().execute(() -> {
                        source.sendFeedback(() -> Text.literal("[NemoCraft] Failed to fetch quests: " + error.getMessage()).formatted(Formatting.RED), false);
                    });
                    return null;
                });

        return 1;
    }

    // -- /nemo quest accept <id> -------------------------------------------

    private static int executeAccept(CommandContext<ServerCommandSource> context) {
        ServerCommandSource source = context.getSource();
        if (!(source.getEntity() instanceof ServerPlayerEntity player)) {
            source.sendFeedback(() -> Text.literal("[NemoCraft] Must be run by a player."), false);
            return 0;
        }

        String uuid = player.getUuidAsString();
        String questId = StringArgumentType.getString(context, "quest_id");

        source.sendFeedback(() -> Text.literal("[NemoCraft] ").formatted(Formatting.GOLD)
                .append(Text.literal("Accepting quest...").formatted(Formatting.YELLOW)), false);

        BackendClient.acceptQuest(uuid, questId)
                .thenAccept(response -> {
                    source.getServer().execute(() -> {
                        String status = response.has("status") ? response.get("status").getAsString() : "error";
                        String msg = response.has("message") ? response.get("message").getAsString() : "Unknown error";
                        if ("ok".equals(status)) {
                            source.sendFeedback(() -> Text.literal("[NemoCraft] ").formatted(Formatting.GOLD)
                                    .append(Text.literal(msg).formatted(Formatting.GREEN)), false);
                            // Show objectives
                            if (response.has("quest")) {
                                JsonObject q = response.getAsJsonObject("quest");
                                displayObjectives(source, q);
                            }
                        } else {
                            source.sendFeedback(() -> Text.literal("[NemoCraft] " + msg).formatted(Formatting.RED), false);
                        }
                    });
                })
                .exceptionally(error -> {
                    source.getServer().execute(() -> {
                        source.sendFeedback(() -> Text.literal("[NemoCraft] Failed: " + error.getMessage()).formatted(Formatting.RED), false);
                    });
                    return null;
                });

        return 1;
    }

    // -- /nemo quest complete <id> -----------------------------------------

    private static int executeComplete(CommandContext<ServerCommandSource> context) {
        ServerCommandSource source = context.getSource();
        if (!(source.getEntity() instanceof ServerPlayerEntity player)) {
            source.sendFeedback(() -> Text.literal("[NemoCraft] Must be run by a player."), false);
            return 0;
        }

        String uuid = player.getUuidAsString();
        String questId = StringArgumentType.getString(context, "quest_id");
        double x = player.getX();
        double y = player.getY();
        double z = player.getZ();

        source.sendFeedback(() -> Text.literal("[NemoCraft] ").formatted(Formatting.GOLD)
                .append(Text.literal("Completing quest and building destination...").formatted(Formatting.YELLOW)), false);

        BackendClient.completeQuest(uuid, questId, x, y, z)
                .thenAccept(response -> {
                    source.getServer().execute(() -> {
                        String status = response.has("status") ? response.get("status").getAsString() : "error";
                        String msg = response.has("message") ? response.get("message").getAsString() : "Unknown error";
                        if ("ok".equals(status)) {
                            source.sendFeedback(() -> Text.literal("[NemoCraft] ").formatted(Formatting.GOLD)
                                    .append(Text.literal(msg).formatted(Formatting.GREEN)), false);
                            // Show rewards
                            if (response.has("rewards")) {
                                JsonObject rewards = response.getAsJsonObject("rewards");
                                displayRewards(source, rewards);
                            }
                        } else {
                            source.sendFeedback(() -> Text.literal("[NemoCraft] " + msg).formatted(Formatting.RED), false);
                        }
                    });
                })
                .exceptionally(error -> {
                    source.getServer().execute(() -> {
                        source.sendFeedback(() -> Text.literal("[NemoCraft] Failed: " + error.getMessage()).formatted(Formatting.RED), false);
                    });
                    return null;
                });

        return 1;
    }

    // -- display helpers ---------------------------------------------------

    private static void displayQuestSummary(ServerCommandSource source, JsonObject quest) {
        String id = quest.has("quest_id") ? quest.get("quest_id").getAsString() : "???";
        String name = quest.has("name") ? quest.get("name").getAsString() : "Unknown Quest";
        String giver = quest.has("giver") ? quest.get("giver").getAsString() : "Unknown";
        String dest = quest.has("destination_type") ? quest.get("destination_type").getAsString() : "unknown";
        int difficulty = quest.has("difficulty") ? quest.get("difficulty").getAsInt() : 1;

        source.sendFeedback(() -> Text.literal("")
                .append(Text.literal(" [" + id + "] ").formatted(Formatting.DARK_GRAY))
                .append(Text.literal(name).formatted(Formatting.GOLD, Formatting.BOLD))
                .append(Text.literal(" (Difficulty " + difficulty + ")").formatted(Formatting.GRAY)), false);
        source.sendFeedback(() -> Text.literal("   From: ").formatted(Formatting.GRAY)
                .append(Text.literal(giver).formatted(Formatting.WHITE))
                .append(Text.literal("  |  Leads to: ").formatted(Formatting.GRAY))
                .append(Text.literal(dest).formatted(Formatting.AQUA)), false);
    }

    private static void displayQuestDetail(ServerCommandSource source, JsonObject quest) {
        String id = quest.has("quest_id") ? quest.get("quest_id").getAsString() : "???";
        String name = quest.has("name") ? quest.get("name").getAsString() : "Unknown Quest";
        String desc = quest.has("description") ? quest.get("description").getAsString() : "";
        String status = quest.has("status") ? quest.get("status").getAsString() : "unknown";
        String giver = quest.has("giver") ? quest.get("giver").getAsString() : "Unknown";

        Formatting statusColor = "active".equals(status) ? Formatting.GREEN : Formatting.YELLOW;
        String statusLabel = "active".equals(status) ? "ACTIVE" : "AVAILABLE";

        source.sendFeedback(() -> Text.literal("")
                .append(Text.literal(" [" + id + "] ").formatted(Formatting.DARK_GRAY))
                .append(Text.literal(name).formatted(Formatting.GOLD, Formatting.BOLD))
                .append(Text.literal(" [" + statusLabel + "]").formatted(statusColor)), false);
        source.sendFeedback(() -> Text.literal("   ").append(Text.literal(desc).formatted(Formatting.GRAY)), false);
        source.sendFeedback(() -> Text.literal("   Quest giver: ").formatted(Formatting.DARK_GRAY)
                .append(Text.literal(giver).formatted(Formatting.WHITE)), false);

        displayObjectives(source, quest);
    }

    private static void displayObjectives(ServerCommandSource source, JsonObject quest) {
        if (!quest.has("objectives")) return;
        JsonArray objectives = quest.getAsJsonArray("objectives");
        for (JsonElement objElem : objectives) {
            JsonObject obj = objElem.getAsJsonObject();
            String objDesc = obj.has("description") ? obj.get("description").getAsString() : "???";
            int current = obj.has("current_count") ? obj.get("current_count").getAsInt() : 0;
            int target = obj.has("target_count") ? obj.get("target_count").getAsInt() : 1;
            boolean done = current >= target;

            Formatting color = done ? Formatting.GREEN : Formatting.WHITE;
            String check = done ? "\u2714 " : "\u2022 ";

            source.sendFeedback(() -> Text.literal("   " + check).formatted(color)
                    .append(Text.literal(objDesc).formatted(color))
                    .append(Text.literal(" (" + current + "/" + target + ")").formatted(Formatting.DARK_GRAY)), false);
        }
    }

    private static void displayRewards(ServerCommandSource source, JsonObject rewards) {
        source.sendFeedback(() -> Text.literal("   Rewards:").formatted(Formatting.GOLD), false);
        if (rewards.has("items")) {
            JsonArray items = rewards.getAsJsonArray("items");
            StringBuilder itemStr = new StringBuilder();
            for (JsonElement item : items) {
                if (itemStr.length() > 0) itemStr.append(", ");
                // Strip "minecraft:" prefix for readability
                String itemName = item.getAsString().replace("minecraft:", "").replace("_", " ");
                itemStr.append(itemName);
            }
            String finalItems = itemStr.toString();
            source.sendFeedback(() -> Text.literal("   Items: ").formatted(Formatting.GRAY)
                    .append(Text.literal(finalItems).formatted(Formatting.AQUA)), false);
        }
        if (rewards.has("experience") && rewards.get("experience").getAsInt() > 0) {
            int xp = rewards.get("experience").getAsInt();
            source.sendFeedback(() -> Text.literal("   XP: ").formatted(Formatting.GRAY)
                    .append(Text.literal("+" + xp).formatted(Formatting.GREEN)), false);
        }
    }
}
