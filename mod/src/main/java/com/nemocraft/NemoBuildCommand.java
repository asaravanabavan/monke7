package com.nemocraft;

import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.context.CommandContext;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.server.command.CommandManager;
import net.minecraft.server.command.ServerCommandSource;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.text.Text;
import net.minecraft.util.Identifier;
import net.minecraft.registry.RegistryKey;
import net.minecraft.registry.RegistryKeys;
import net.minecraft.util.math.BlockPos;

public class NemoBuildCommand {

    public static void register() {
        CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> {
            dispatcher.register(
                CommandManager.literal("nemo")
                    .then(CommandManager.literal("build")
                        .then(CommandManager.argument("prompt", StringArgumentType.greedyString())
                            .executes(NemoBuildCommand::executeBuild)
                        )
                    )
            );
        });
        NemoCraft.LOGGER.info("[NemoCraft] Command /nemo build registered");
    }

    private static int executeBuild(CommandContext<ServerCommandSource> context) {
        ServerCommandSource source = context.getSource();
        String prompt = StringArgumentType.getString(context, "prompt");

        // Must be run by a player
        if (!(source.getEntity() instanceof ServerPlayerEntity player)) {
            source.sendFeedback(() -> Text.literal("[NemoCraft] This command must be run by a player."), false);
            return 0;
        }

        String playerName = player.getName().getString();
        String playerUuid = player.getUuidAsString();
        BlockPos pos = player.getBlockPos();
        double x = pos.getX();
        double y = pos.getY();
        double z = pos.getZ();

        // Get biome
        Identifier biomeId = player.getWorld().getBiome(pos).getKey()
                .map(RegistryKey::getValue)
                .orElse(new Identifier("minecraft", "plains"));
        String biome = biomeId.toString();

        source.sendFeedback(() -> Text.literal("[NemoCraft] Generating dungeon: \"" + prompt + "\"..."), true);

        // Async HTTP call
        BackendClient.requestBuild(prompt, playerName, playerUuid, x, y, z, biome)
                .thenAccept(response -> {
                    // Route response back to server thread
                    source.getServer().execute(() -> {
                        if (response.has("error")) {
                            source.sendFeedback(() -> Text.literal("[NemoCraft] Error: " + response.get("error").getAsString()), false);
                        } else {
                            String name = response.has("name") ? response.get("name").getAsString() : "dungeon";
                            int roomCount = response.has("room_count") ? response.get("room_count").getAsInt() : 0;
                            source.sendFeedback(() -> Text.literal("[NemoCraft] Built \"" + name + "\" with " + roomCount + " rooms!"), true);
                        }
                    });
                })
                .exceptionally(error -> {
                    source.getServer().execute(() -> {
                        source.sendFeedback(() -> Text.literal("[NemoCraft] Failed to contact backend: " + error.getMessage()), false);
                    });
                    return null;
                });

        return 1;
    }
}
