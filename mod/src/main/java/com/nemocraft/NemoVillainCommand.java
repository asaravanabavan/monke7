package com.nemocraft;

import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.context.CommandContext;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.server.command.CommandManager;
import net.minecraft.server.command.ServerCommandSource;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.text.Text;
import net.minecraft.util.Formatting;

/**
 * Registers villain-related subcommands under /nemo:
 *
 *   /nemo villain          - show villain status
 *   /nemo villain on       - enable villain (op-only)
 *   /nemo villain off      - disable villain (op-only)
 *   /nemo villain say <msg> - directly talk to the villain
 */
public class NemoVillainCommand {

    public static void register() {
        CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> {
            dispatcher.register(
                CommandManager.literal("nemo")
                    .then(CommandManager.literal("villain")
                        // /nemo villain — show status
                        .executes(NemoVillainCommand::executeStatus)
                        // /nemo villain on — enable (op-only)
                        .then(CommandManager.literal("on")
                            .requires(source -> source.hasPermissionLevel(2))
                            .executes(NemoVillainCommand::executeOn)
                        )
                        // /nemo villain off — disable (op-only)
                        .then(CommandManager.literal("off")
                            .requires(source -> source.hasPermissionLevel(2))
                            .executes(NemoVillainCommand::executeOff)
                        )
                        // /nemo villain say <message> — direct talk
                        .then(CommandManager.literal("say")
                            .then(CommandManager.argument("message", StringArgumentType.greedyString())
                                .executes(NemoVillainCommand::executeSay)
                            )
                        )
                    )
            );
        });
        NemoCraft.LOGGER.info("[NemoCraft] Villain commands registered");
    }

    // -- /nemo villain (status) --------------------------------------------

    private static int executeStatus(CommandContext<ServerCommandSource> context) {
        ServerCommandSource source = context.getSource();
        boolean enabled = VillainChatHandler.isEnabled();

        Formatting statusColor = enabled ? Formatting.GREEN : Formatting.RED;
        String statusText = enabled ? "ACTIVE" : "DISABLED";

        source.sendFeedback(() -> Text.literal("[NemoCraft] ").formatted(Formatting.GOLD)
                .append(Text.literal("Lord Netherbane is ").formatted(Formatting.GRAY))
                .append(Text.literal(statusText).formatted(statusColor, Formatting.BOLD)), false);

        if (enabled) {
            source.sendFeedback(() -> Text.literal("  Mention ").formatted(Formatting.GRAY)
                    .append(Text.literal("\"netherbane\"").formatted(Formatting.RED))
                    .append(Text.literal(" in chat or use ").formatted(Formatting.GRAY))
                    .append(Text.literal("/nemo villain say <msg>").formatted(Formatting.YELLOW))
                    .append(Text.literal(" to taunt him!").formatted(Formatting.GRAY)), false);
        }

        return 1;
    }

    // -- /nemo villain on --------------------------------------------------

    private static int executeOn(CommandContext<ServerCommandSource> context) {
        ServerCommandSource source = context.getSource();
        VillainChatHandler.setEnabled(true);
        source.sendFeedback(() -> Text.literal("[NemoCraft] ").formatted(Formatting.GOLD)
                .append(Text.literal("Lord Netherbane has entered the realm! MWAHAHAHA!").formatted(Formatting.DARK_RED, Formatting.BOLD)), false);
        return 1;
    }

    // -- /nemo villain off -------------------------------------------------

    private static int executeOff(CommandContext<ServerCommandSource> context) {
        ServerCommandSource source = context.getSource();
        VillainChatHandler.setEnabled(false);
        source.sendFeedback(() -> Text.literal("[NemoCraft] ").formatted(Formatting.GOLD)
                .append(Text.literal("Lord Netherbane retreats to the shadows...").formatted(Formatting.GRAY)), false);
        return 1;
    }

    // -- /nemo villain say <message> ---------------------------------------

    private static int executeSay(CommandContext<ServerCommandSource> context) {
        ServerCommandSource source = context.getSource();
        if (!(source.getEntity() instanceof ServerPlayerEntity player)) {
            source.sendFeedback(() -> Text.literal("[NemoCraft] Must be run by a player."), false);
            return 0;
        }

        if (!VillainChatHandler.isEnabled()) {
            source.sendFeedback(() -> Text.literal("[NemoCraft] ").formatted(Formatting.GOLD)
                    .append(Text.literal("Lord Netherbane is not active. Use ").formatted(Formatting.GRAY))
                    .append(Text.literal("/nemo villain on").formatted(Formatting.YELLOW))
                    .append(Text.literal(" to summon him (op-only).").formatted(Formatting.GRAY)), false);
            return 0;
        }

        String message = StringArgumentType.getString(context, "message");
        String uuid = player.getUuidAsString();
        String name = player.getName().getString();
        double x = player.getX();
        double y = player.getY();
        double z = player.getZ();

        source.sendFeedback(() -> Text.literal("[You -> Lord Netherbane] ").formatted(Formatting.DARK_GRAY)
                .append(Text.literal(message).formatted(Formatting.WHITE)), false);

        BackendClient.villainChat(uuid, name, message, x, y, z)
                .thenAccept(response -> {
                    source.getServer().execute(() -> {
                        if (response.has("status") && "disabled".equals(response.get("status").getAsString())) {
                            source.sendFeedback(() -> Text.literal("[NemoCraft] Villain is disabled on the backend.").formatted(Formatting.RED), false);
                        } else if (response.has("dialogue") && !response.get("dialogue").isJsonNull()) {
                            VillainNetworking.sendVillainSpeakPacket(player);
                        }
                    });
                })
                .exceptionally(error -> {
                    source.getServer().execute(() -> {
                        source.sendFeedback(() -> Text.literal("[NemoCraft] Failed to reach Lord Netherbane: " + error.getMessage()).formatted(Formatting.RED), false);
                    });
                    return null;
                });

        return 1;
    }
}
