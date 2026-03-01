package com.nemocraft;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.fabricmc.fabric.api.client.rendering.v1.HudRenderCallback;

/**
 * Client entrypoint for NemoCraft. Registers HUD overlay and network receivers.
 */
public class NemoCraftClient implements ClientModInitializer {

    @Override
    public void onInitializeClient() {
        // Register HUD overlay renderer
        HudRenderCallback.EVENT.register(VillainOverlayRenderer::render);

        // Register S2C packet receiver for villain speak events
        ClientPlayNetworking.registerGlobalReceiver(VillainNetworking.VILLAIN_SPEAK_ID, (client, handler, buf, responseSender) -> {
            client.execute(VillainOverlayRenderer::trigger);
        });
    }
}
