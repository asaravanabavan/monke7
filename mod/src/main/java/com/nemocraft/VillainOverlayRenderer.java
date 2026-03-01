package com.nemocraft;

import com.mojang.blaze3d.systems.RenderSystem;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.util.Identifier;

/**
 * Client-side HUD renderer that shows the villain portrait when triggered.
 * Shows for 60 ticks (3 sec), fading out over the last 20 ticks.
 */
public class VillainOverlayRenderer {

    private static final Identifier PORTRAIT_TEXTURE = new Identifier("nemocraft", "textures/gui/agent_of_doom.png");
    private static final int DISPLAY_TICKS = 60;
    private static final int FADE_TICKS = 20;
    private static final int SIZE = 128;
    private static final int MARGIN = 10;

    private static int ticksRemaining = 0;

    /** Called from the network receiver to trigger the portrait display. */
    public static void trigger() {
        ticksRemaining = DISPLAY_TICKS;
    }

    /** Called every frame from HudRenderCallback. */
    public static void render(DrawContext context, float tickDelta) {
        if (ticksRemaining <= 0) return;

        MinecraftClient client = MinecraftClient.getInstance();
        int screenWidth = client.getWindow().getScaledWidth();

        int x = screenWidth - SIZE - MARGIN;
        int y = MARGIN;

        // Calculate alpha: full opacity until last FADE_TICKS, then fade out
        float alpha;
        if (ticksRemaining <= FADE_TICKS) {
            alpha = (float) ticksRemaining / FADE_TICKS;
        } else {
            alpha = 1.0f;
        }

        RenderSystem.enableBlend();
        RenderSystem.defaultBlendFunc();
        RenderSystem.setShaderColor(1.0f, 1.0f, 1.0f, alpha);

        context.drawTexture(PORTRAIT_TEXTURE, x, y, 0, 0, SIZE, SIZE, SIZE, SIZE);

        RenderSystem.setShaderColor(1.0f, 1.0f, 1.0f, 1.0f);
        RenderSystem.disableBlend();

        // Decrement once per tick (not per frame)
        // HudRenderCallback fires every frame, so use tickDelta to approximate tick boundaries
        ticksRemaining--;
    }
}
