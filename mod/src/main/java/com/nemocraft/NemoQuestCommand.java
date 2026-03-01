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
 *   /nemo quest              — Generate new quests
 *   /nemo quests             — List active quests (quest journal)
 *   /nemo quest accept <id>  — Accept a quest
 *   /nemo quest complete <id> — Complete a quest and build its destination
 */
public class NemoQuestCommand {

    // ── Visual constants ─────────────────────────────────────────────────
    private static final String LINE_THICK  = "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"; // ════...
    private static final String LINE_THIN   = "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"; // ────...
    private static final String ICON_SCROLL = "\u270E";  // ✎
    private static final String ICON_SWORD  = "\u2694";  // ⚔
    private static final String ICON_STAR   = "\u2605";  // ★
    private static final String ICON_CHECK  = "\u2714";  // ✔
    private static final String ICON_ARROW  = "\u25B6";  // ▶
    private static final String ICON_DOT    = "\u25CF";  // ●
    private static final String ICON_CIRCLE = "\u25CB";  // ○
    private static final String ICON_CHEST  = "\u25A0";  // ■
    private static final String ICON_TROPHY = "\u2655";  // ♕

    public static void register() {
        CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> {
            dispatcher.register(
                CommandManager.literal("nemo")
                    .then(CommandManager.literal("quest")
                        .executes(NemoQuestCommand::executeGenerate)
                        .then(CommandManager.literal("accept")
                            .then(CommandManager.argument("quest_id", StringArgumentType.word())
                                .executes(NemoQuestCommand::executeAccept)
                            )
                        )
                        .then(CommandManager.literal("complete")
                            .then(CommandManager.argument("quest_id", StringArgumentType.word())
                                .executes(NemoQuestCommand::executeComplete)
                            )
                        )
                    )
                    .then(CommandManager.literal("quests")
                        .executes(NemoQuestCommand::executeList)
                    )
            );
        });
        NemoCraft.LOGGER.info("[NemoCraft] Quest commands registered");
    }

    // ── /nemo quest (generate) ───────────────────────────────────────────

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

        source.sendFeedback(() -> Text.literal("")
                .append(Text.literal(ICON_SCROLL + " ").formatted(Formatting.GOLD))
                .append(Text.literal("Consulting the quest board...").formatted(Formatting.YELLOW, Formatting.ITALIC)), false);

        BackendClient.generateQuests(uuid, name, x, y, z)
                .thenAccept(response -> {
                    source.getServer().execute(() -> {
                        if (response.has("quests")) {
                            JsonArray quests = response.getAsJsonArray("quests");
                            if (quests.isEmpty()) {
                                send(source, Text.literal(ICON_SCROLL + " ").formatted(Formatting.GOLD)
                                        .append(Text.literal("The quest board is empty. Check back later or complete existing quests.").formatted(Formatting.GRAY)));
                                return;
                            }

                            // Header
                            send(source, Text.literal(LINE_THICK).formatted(Formatting.GOLD));
                            send(source, Text.literal("  " + ICON_SCROLL + " ").formatted(Formatting.GOLD)
                                    .append(Text.literal("NEW QUESTS AVAILABLE").formatted(Formatting.GOLD, Formatting.BOLD))
                                    .append(Text.literal("  " + ICON_SCROLL).formatted(Formatting.GOLD)));
                            send(source, Text.literal(LINE_THICK).formatted(Formatting.GOLD));

                            for (JsonElement elem : quests) {
                                displayQuestCard(source, elem.getAsJsonObject(), false);
                            }

                            // Footer
                            send(source, Text.literal(LINE_THIN).formatted(Formatting.DARK_GRAY));
                            send(source, Text.literal("  " + ICON_ARROW + " ").formatted(Formatting.YELLOW)
                                    .append(Text.literal("Type ").formatted(Formatting.GRAY))
                                    .append(Text.literal("/nemo quest accept <id>").formatted(Formatting.YELLOW, Formatting.BOLD))
                                    .append(Text.literal(" to begin a quest").formatted(Formatting.GRAY)));
                            send(source, Text.literal(LINE_THICK).formatted(Formatting.GOLD));
                        } else {
                            String msg = response.has("message") ? response.get("message").getAsString() : "Unknown error";
                            send(source, Text.literal("[NemoCraft] " + msg).formatted(Formatting.RED));
                        }
                    });
                })
                .exceptionally(error -> {
                    source.getServer().execute(() ->
                        send(source, Text.literal("[NemoCraft] Failed to generate quests: " + error.getMessage()).formatted(Formatting.RED)));
                    return null;
                });

        return 1;
    }

    // ── /nemo quests (journal) ───────────────────────────────────────────

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
                        if (quests.isEmpty()) {
                            send(source, Text.literal(LINE_THIN).formatted(Formatting.DARK_GRAY));
                            send(source, Text.literal("  " + ICON_SCROLL + " ").formatted(Formatting.GRAY)
                                    .append(Text.literal("Your quest journal is empty.").formatted(Formatting.GRAY)));
                            send(source, Text.literal("  " + ICON_ARROW + " ").formatted(Formatting.YELLOW)
                                    .append(Text.literal("Use ").formatted(Formatting.GRAY))
                                    .append(Text.literal("/nemo quest").formatted(Formatting.YELLOW))
                                    .append(Text.literal(" to find new quests!").formatted(Formatting.GRAY)));
                            send(source, Text.literal(LINE_THIN).formatted(Formatting.DARK_GRAY));
                            return;
                        }

                        // Header
                        send(source, Text.literal(LINE_THICK).formatted(Formatting.AQUA));
                        send(source, Text.literal("  " + ICON_SCROLL + " ").formatted(Formatting.AQUA)
                                .append(Text.literal("QUEST JOURNAL").formatted(Formatting.AQUA, Formatting.BOLD))
                                .append(Text.literal("  (" + quests.size() + " active)").formatted(Formatting.DARK_AQUA)));
                        send(source, Text.literal(LINE_THICK).formatted(Formatting.AQUA));

                        for (JsonElement elem : quests) {
                            displayQuestCard(source, elem.getAsJsonObject(), true);
                        }

                        send(source, Text.literal(LINE_THICK).formatted(Formatting.AQUA));
                    });
                })
                .exceptionally(error -> {
                    source.getServer().execute(() ->
                        send(source, Text.literal("[NemoCraft] Failed to fetch quests: " + error.getMessage()).formatted(Formatting.RED)));
                    return null;
                });

        return 1;
    }

    // ── /nemo quest accept <id> ──────────────────────────────────────────

    private static int executeAccept(CommandContext<ServerCommandSource> context) {
        ServerCommandSource source = context.getSource();
        if (!(source.getEntity() instanceof ServerPlayerEntity player)) {
            source.sendFeedback(() -> Text.literal("[NemoCraft] Must be run by a player."), false);
            return 0;
        }

        String uuid = player.getUuidAsString();
        String questId = StringArgumentType.getString(context, "quest_id");

        send(source, Text.literal(ICON_SCROLL + " ").formatted(Formatting.GOLD)
                .append(Text.literal("Accepting quest...").formatted(Formatting.YELLOW)));

        BackendClient.acceptQuest(uuid, questId)
                .thenAccept(response -> {
                    source.getServer().execute(() -> {
                        String status = response.has("status") ? response.get("status").getAsString() : "error";
                        String msg = response.has("message") ? response.get("message").getAsString() : "Unknown error";
                        if ("ok".equals(status)) {
                            send(source, Text.literal(LINE_THIN).formatted(Formatting.GREEN));
                            send(source, Text.literal("  " + ICON_STAR + " ").formatted(Formatting.GREEN)
                                    .append(Text.literal("QUEST ACCEPTED").formatted(Formatting.GREEN, Formatting.BOLD)));

                            if (response.has("quest")) {
                                JsonObject q = response.getAsJsonObject("quest");
                                String qName = q.has("name") ? q.get("name").getAsString() : "Unknown";
                                send(source, Text.literal("  ").append(Text.literal(qName).formatted(Formatting.GOLD, Formatting.BOLD)));
                                send(source, Text.literal(""));
                                send(source, Text.literal("  Objectives:").formatted(Formatting.WHITE, Formatting.UNDERLINE));
                                displayObjectives(source, q);

                                if (q.has("rewards")) {
                                    send(source, Text.literal(""));
                                    displayRewards(source, q.getAsJsonObject("rewards"));
                                }
                            }
                            send(source, Text.literal(LINE_THIN).formatted(Formatting.GREEN));
                        } else {
                            send(source, Text.literal("[NemoCraft] " + msg).formatted(Formatting.RED));
                        }
                    });
                })
                .exceptionally(error -> {
                    source.getServer().execute(() ->
                        send(source, Text.literal("[NemoCraft] Failed: " + error.getMessage()).formatted(Formatting.RED)));
                    return null;
                });

        return 1;
    }

    // ── /nemo quest complete <id> ────────────────────────────────────────

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

        send(source, Text.literal(ICON_SWORD + " ").formatted(Formatting.GOLD)
                .append(Text.literal("Completing quest — building your reward...").formatted(Formatting.YELLOW, Formatting.ITALIC)));

        BackendClient.completeQuest(uuid, questId, x, y, z)
                .thenAccept(response -> {
                    source.getServer().execute(() -> {
                        String status = response.has("status") ? response.get("status").getAsString() : "error";
                        String msg = response.has("message") ? response.get("message").getAsString() : "Unknown error";
                        if ("ok".equals(status)) {
                            send(source, Text.literal(LINE_THICK).formatted(Formatting.LIGHT_PURPLE));
                            send(source, Text.literal("  " + ICON_TROPHY + " ").formatted(Formatting.LIGHT_PURPLE)
                                    .append(Text.literal("QUEST COMPLETE!").formatted(Formatting.LIGHT_PURPLE, Formatting.BOLD)));
                            send(source, Text.literal("  ").append(Text.literal(msg).formatted(Formatting.WHITE)));

                            if (response.has("rewards")) {
                                send(source, Text.literal(""));
                                displayRewards(source, response.getAsJsonObject("rewards"));
                            }

                            if (response.has("structure_built")) {
                                JsonObject built = response.getAsJsonObject("structure_built");
                                String bName = built.has("name") ? built.get("name").getAsString() : "structure";
                                int rooms = built.has("room_count") ? built.get("room_count").getAsInt() : 0;
                                send(source, Text.literal(""));
                                send(source, Text.literal("  " + ICON_CHEST + " ").formatted(Formatting.AQUA)
                                        .append(Text.literal("Built: ").formatted(Formatting.GRAY))
                                        .append(Text.literal("\"" + bName + "\"").formatted(Formatting.AQUA, Formatting.BOLD))
                                        .append(Text.literal(" (" + rooms + " rooms)").formatted(Formatting.DARK_GRAY)));
                            }
                            send(source, Text.literal(LINE_THICK).formatted(Formatting.LIGHT_PURPLE));
                        } else {
                            send(source, Text.literal("[NemoCraft] " + msg).formatted(Formatting.RED));
                        }
                    });
                })
                .exceptionally(error -> {
                    source.getServer().execute(() ->
                        send(source, Text.literal("[NemoCraft] Failed: " + error.getMessage()).formatted(Formatting.RED)));
                    return null;
                });

        return 1;
    }

    // ── Display helpers ──────────────────────────────────────────────────

    /**
     * Display a single quest as a formatted card.
     * When showDetail is true, includes description and full objective progress.
     */
    private static void displayQuestCard(ServerCommandSource source, JsonObject quest, boolean showDetail) {
        String id = quest.has("quest_id") ? quest.get("quest_id").getAsString() : "???";
        String name = quest.has("name") ? quest.get("name").getAsString() : "Unknown Quest";
        String desc = quest.has("description") ? quest.get("description").getAsString() : "";
        String giver = quest.has("giver") ? quest.get("giver").getAsString() : "Unknown";
        String status = quest.has("status") ? quest.get("status").getAsString() : "available";
        String dest = quest.has("destination_type") ? quest.get("destination_type").getAsString() : "unknown";
        int difficulty = quest.has("difficulty") ? quest.get("difficulty").getAsInt() : 1;

        send(source, Text.literal(""));

        // Status badge
        Formatting statusColor;
        String statusIcon;
        String statusLabel;
        switch (status) {
            case "active":
                statusColor = Formatting.GREEN;
                statusIcon = ICON_SWORD;
                statusLabel = "ACTIVE";
                break;
            case "completed":
                statusColor = Formatting.LIGHT_PURPLE;
                statusIcon = ICON_CHECK;
                statusLabel = "COMPLETE";
                break;
            default:
                statusColor = Formatting.YELLOW;
                statusIcon = ICON_CIRCLE;
                statusLabel = "AVAILABLE";
                break;
        }

        // Quest name line with status and difficulty
        MutableText nameLine = Text.literal("  " + statusIcon + " ").formatted(statusColor)
                .append(Text.literal(name).formatted(Formatting.GOLD, Formatting.BOLD))
                .append(Text.literal("  ").formatted(Formatting.DARK_GRAY))
                .append(Text.literal("[" + statusLabel + "]").formatted(statusColor));
        send(source, nameLine);

        // Difficulty bar + destination
        String difficultyBar = buildDifficultyBar(difficulty);
        Formatting diffColor = difficulty <= 3 ? Formatting.GREEN : difficulty <= 6 ? Formatting.YELLOW : Formatting.RED;
        send(source, Text.literal("  Difficulty: ").formatted(Formatting.DARK_GRAY)
                .append(Text.literal(difficultyBar).formatted(diffColor))
                .append(Text.literal("  " + ICON_ARROW + " ").formatted(Formatting.DARK_GRAY))
                .append(Text.literal(formatDestination(dest)).formatted(Formatting.AQUA)));

        // ID + Quest giver
        send(source, Text.literal("  ID: ").formatted(Formatting.DARK_GRAY)
                .append(Text.literal(id).formatted(Formatting.GRAY))
                .append(Text.literal("  |  From: ").formatted(Formatting.DARK_GRAY))
                .append(Text.literal(giver).formatted(Formatting.WHITE, Formatting.ITALIC)));

        // Description (in detail mode)
        if (showDetail && !desc.isEmpty()) {
            send(source, Text.literal("  \"").formatted(Formatting.DARK_GRAY)
                    .append(Text.literal(desc).formatted(Formatting.GRAY, Formatting.ITALIC))
                    .append(Text.literal("\"").formatted(Formatting.DARK_GRAY)));
        }

        // Objectives
        if (showDetail || "active".equals(status)) {
            displayObjectives(source, quest);
        }

        // Reward preview (brief)
        if (quest.has("rewards") && showDetail) {
            displayRewards(source, quest.getAsJsonObject("rewards"));
        }

        send(source, Text.literal("  " + LINE_THIN.substring(0, 30)).formatted(Formatting.DARK_GRAY));
    }

    private static void displayObjectives(ServerCommandSource source, JsonObject quest) {
        if (!quest.has("objectives")) return;
        JsonArray objectives = quest.getAsJsonArray("objectives");

        for (JsonElement objElem : objectives) {
            JsonObject obj = objElem.getAsJsonObject();
            String objDesc = obj.has("description") ? obj.get("description").getAsString() : "???";
            String objType = obj.has("objective_type") ? obj.get("objective_type").getAsString() : "";
            int current = obj.has("current_count") ? obj.get("current_count").getAsInt() : 0;
            int target = obj.has("target_count") ? obj.get("target_count").getAsInt() : 1;
            boolean done = current >= target;

            String typeIcon = getObjectiveIcon(objType);
            Formatting color = done ? Formatting.GREEN : Formatting.WHITE;
            String progressIcon = done ? ICON_CHECK : ICON_DOT;

            // Progress bar for multi-count objectives
            String progressText;
            if (target > 1) {
                progressText = " [" + buildProgressBar(current, target) + "] " + current + "/" + target;
            } else {
                progressText = done ? " Done" : " " + current + "/" + target;
            }

            send(source, Text.literal("    " + progressIcon + " ").formatted(color)
                    .append(Text.literal(typeIcon + " ").formatted(Formatting.DARK_AQUA))
                    .append(Text.literal(objDesc).formatted(color))
                    .append(Text.literal(progressText).formatted(done ? Formatting.GREEN : Formatting.DARK_GRAY)));
        }
    }

    private static void displayRewards(ServerCommandSource source, JsonObject rewards) {
        send(source, Text.literal("  " + ICON_CHEST + " Rewards:").formatted(Formatting.GOLD));

        if (rewards.has("items")) {
            JsonArray items = rewards.getAsJsonArray("items");
            for (JsonElement item : items) {
                String itemName = item.getAsString().replace("minecraft:", "").replace("_", " ");
                // Capitalize first letter of each word
                String[] words = itemName.split(" ");
                StringBuilder formatted = new StringBuilder();
                for (String word : words) {
                    if (formatted.length() > 0) formatted.append(" ");
                    formatted.append(word.substring(0, 1).toUpperCase()).append(word.substring(1));
                }
                send(source, Text.literal("    " + ICON_STAR + " ").formatted(Formatting.AQUA)
                        .append(Text.literal(formatted.toString()).formatted(Formatting.WHITE)));
            }
        }
        if (rewards.has("experience") && rewards.get("experience").getAsInt() > 0) {
            int xp = rewards.get("experience").getAsInt();
            send(source, Text.literal("    " + ICON_STAR + " ").formatted(Formatting.GREEN)
                    .append(Text.literal("+" + xp + " XP").formatted(Formatting.GREEN, Formatting.BOLD)));
        }
    }

    // ── Formatting utilities ─────────────────────────────────────────────

    private static void send(ServerCommandSource source, MutableText text) {
        source.sendFeedback(() -> text, false);
    }

    /**
     * Build a visual difficulty bar: ■■■■■□□□□□ (filled/empty out of 10)
     */
    private static String buildDifficultyBar(int difficulty) {
        StringBuilder bar = new StringBuilder();
        for (int i = 0; i < 10; i++) {
            bar.append(i < difficulty ? "\u25A0" : "\u25A1"); // ■ or □
        }
        return bar.toString();
    }

    /**
     * Build a mini progress bar: ████░░░░ (8 chars wide)
     */
    private static String buildProgressBar(int current, int target) {
        int barWidth = 8;
        int filled = target > 0 ? (current * barWidth / target) : 0;
        filled = Math.min(filled, barWidth);
        StringBuilder bar = new StringBuilder();
        for (int i = 0; i < barWidth; i++) {
            bar.append(i < filled ? "\u2588" : "\u2591"); // █ or ░
        }
        return bar.toString();
    }

    /**
     * Map objective type to a visual icon character.
     */
    private static String getObjectiveIcon(String type) {
        return switch (type) {
            case "kill"          -> "\u2620"; // ☠
            case "explore"       -> "\u2302"; // ⌂
            case "collect"       -> "\u2666"; // ♦
            case "escort"        -> "\u2665"; // ♥
            case "build"         -> "\u2692"; // ⚒
            case "survive"       -> "\u2764"; // ❤
            case "clear_dungeon" -> "\u2694"; // ⚔
            default              -> "\u25CF"; // ●
        };
    }

    /**
     * Format destination type for display (capitalize, prettify).
     */
    private static String formatDestination(String dest) {
        if (dest == null || dest.isEmpty()) return "Unknown";
        return dest.substring(0, 1).toUpperCase() + dest.substring(1).replace("_", " ");
    }
}
