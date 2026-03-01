package com.nemocraft;

import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.fabricmc.fabric.api.networking.v1.PacketByteBufs;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.util.Identifier;

/**
 * Shared networking channel and server-side send helper for villain portrait overlay.
 */
public class VillainNetworking {

    public static final Identifier VILLAIN_SPEAK_ID = new Identifier("nemocraft", "villain_speak");

    /**
     * Sends an empty S2C packet to trigger the villain portrait overlay on the client.
     */
    public static void sendVillainSpeakPacket(ServerPlayerEntity player) {
        ServerPlayNetworking.send(player, VILLAIN_SPEAK_ID, PacketByteBufs.empty());
    }
}
