"""
Hardcoded sets of valid Minecraft 1.20.1 IDs for NemoCraft.

Massively expanded to allow the AI maximum creative freedom with block palettes,
mob selections, and loot variety.
"""

# ---------------------------------------------------------------------------
# Blocks (~200+)
# ---------------------------------------------------------------------------
VALID_BLOCK_IDS: set[str] = {
    # Stone palette
    "minecraft:stone", "minecraft:cobblestone", "minecraft:mossy_cobblestone",
    "minecraft:stone_bricks", "minecraft:mossy_stone_bricks",
    "minecraft:cracked_stone_bricks", "minecraft:chiseled_stone_bricks",
    "minecraft:smooth_stone", "minecraft:stone_brick_slab",
    "minecraft:stone_brick_stairs", "minecraft:stone_brick_wall",
    "minecraft:cobblestone_slab", "minecraft:cobblestone_stairs",
    "minecraft:cobblestone_wall",

    # Deepslate palette
    "minecraft:deepslate", "minecraft:deepslate_bricks",
    "minecraft:cobbled_deepslate", "minecraft:polished_deepslate",
    "minecraft:deepslate_tiles", "minecraft:chiseled_deepslate",
    "minecraft:deepslate_brick_slab", "minecraft:deepslate_tile_slab",
    "minecraft:deepslate_brick_stairs", "minecraft:deepslate_tile_stairs",
    "minecraft:deepslate_brick_wall", "minecraft:deepslate_tile_wall",
    "minecraft:cobbled_deepslate_slab", "minecraft:cobbled_deepslate_stairs",
    "minecraft:cobbled_deepslate_wall",

    # Nether palette
    "minecraft:nether_bricks", "minecraft:red_nether_bricks",
    "minecraft:nether_brick_slab", "minecraft:nether_brick_stairs",
    "minecraft:nether_brick_wall", "minecraft:nether_brick_fence",
    "minecraft:soul_sand", "minecraft:soul_soil",
    "minecraft:netherrack", "minecraft:basalt", "minecraft:polished_basalt",
    "minecraft:smooth_basalt",
    "minecraft:blackstone", "minecraft:polished_blackstone",
    "minecraft:polished_blackstone_bricks", "minecraft:gilded_blackstone",
    "minecraft:chiseled_polished_blackstone",
    "minecraft:polished_blackstone_slab", "minecraft:polished_blackstone_stairs",
    "minecraft:polished_blackstone_brick_slab", "minecraft:polished_blackstone_brick_stairs",
    "minecraft:polished_blackstone_wall", "minecraft:polished_blackstone_brick_wall",
    "minecraft:magma_block", "minecraft:glowstone", "minecraft:shroomlight",
    "minecraft:crimson_planks", "minecraft:warped_planks",
    "minecraft:crimson_stem", "minecraft:warped_stem",
    "minecraft:nether_wart_block", "minecraft:warped_wart_block",
    "minecraft:crimson_nylium", "minecraft:warped_nylium",

    # Ocean / Prismarine palette
    "minecraft:prismarine", "minecraft:dark_prismarine",
    "minecraft:prismarine_bricks", "minecraft:sea_lantern",
    "minecraft:prismarine_slab", "minecraft:prismarine_brick_slab",
    "minecraft:dark_prismarine_slab", "minecraft:prismarine_stairs",
    "minecraft:prismarine_brick_stairs", "minecraft:dark_prismarine_stairs",
    "minecraft:prismarine_wall",

    # End palette
    "minecraft:obsidian", "minecraft:crying_obsidian",
    "minecraft:end_stone", "minecraft:end_stone_bricks",
    "minecraft:end_stone_brick_slab", "minecraft:end_stone_brick_stairs",
    "minecraft:end_stone_brick_wall",
    "minecraft:purpur_block", "minecraft:purpur_pillar",
    "minecraft:purpur_slab", "minecraft:purpur_stairs",

    # Sandstone palette
    "minecraft:sandstone", "minecraft:smooth_sandstone",
    "minecraft:chiseled_sandstone", "minecraft:cut_sandstone",
    "minecraft:sandstone_slab", "minecraft:sandstone_stairs", "minecraft:sandstone_wall",
    "minecraft:red_sandstone", "minecraft:smooth_red_sandstone",
    "minecraft:chiseled_red_sandstone", "minecraft:cut_red_sandstone",
    "minecraft:red_sandstone_slab", "minecraft:red_sandstone_stairs",
    "minecraft:red_sandstone_wall",

    # Brick palettes
    "minecraft:bricks", "minecraft:brick_slab", "minecraft:brick_stairs",
    "minecraft:brick_wall",
    "minecraft:mud_bricks", "minecraft:mud_brick_slab",
    "minecraft:mud_brick_stairs", "minecraft:mud_brick_wall",

    # Wood planks (all types)
    "minecraft:oak_planks", "minecraft:spruce_planks", "minecraft:birch_planks",
    "minecraft:dark_oak_planks", "minecraft:jungle_planks", "minecraft:acacia_planks",
    "minecraft:mangrove_planks", "minecraft:cherry_planks",
    "minecraft:oak_log", "minecraft:spruce_log", "minecraft:birch_log",
    "minecraft:dark_oak_log", "minecraft:jungle_log", "minecraft:acacia_log",
    "minecraft:stripped_oak_log", "minecraft:stripped_spruce_log",
    "minecraft:stripped_dark_oak_log",
    "minecraft:oak_slab", "minecraft:spruce_slab", "minecraft:dark_oak_slab",
    "minecraft:oak_stairs", "minecraft:spruce_stairs", "minecraft:dark_oak_stairs",
    "minecraft:oak_fence", "minecraft:spruce_fence", "minecraft:dark_oak_fence",

    # Copper palette
    "minecraft:copper_block", "minecraft:cut_copper",
    "minecraft:exposed_copper", "minecraft:exposed_cut_copper",
    "minecraft:weathered_copper", "minecraft:weathered_cut_copper",
    "minecraft:oxidized_copper", "minecraft:oxidized_cut_copper",
    "minecraft:cut_copper_slab", "minecraft:cut_copper_stairs",
    "minecraft:waxed_copper_block",

    # Metal / ore blocks
    "minecraft:iron_block", "minecraft:gold_block", "minecraft:redstone_block",
    "minecraft:lapis_block", "minecraft:emerald_block", "minecraft:diamond_block",
    "minecraft:netherite_block", "minecraft:raw_iron_block",
    "minecraft:raw_gold_block", "minecraft:raw_copper_block",
    "minecraft:amethyst_block",

    # Concrete (all colors)
    "minecraft:white_concrete", "minecraft:light_gray_concrete",
    "minecraft:gray_concrete", "minecraft:black_concrete",
    "minecraft:red_concrete", "minecraft:orange_concrete",
    "minecraft:yellow_concrete", "minecraft:lime_concrete",
    "minecraft:green_concrete", "minecraft:cyan_concrete",
    "minecraft:light_blue_concrete", "minecraft:blue_concrete",
    "minecraft:purple_concrete", "minecraft:magenta_concrete",
    "minecraft:pink_concrete", "minecraft:brown_concrete",

    # Terracotta (all colors)
    "minecraft:terracotta", "minecraft:white_terracotta",
    "minecraft:light_gray_terracotta", "minecraft:gray_terracotta",
    "minecraft:black_terracotta", "minecraft:red_terracotta",
    "minecraft:orange_terracotta", "minecraft:yellow_terracotta",
    "minecraft:brown_terracotta", "minecraft:cyan_terracotta",

    # Glazed terracotta (select)
    "minecraft:white_glazed_terracotta", "minecraft:blue_glazed_terracotta",
    "minecraft:cyan_glazed_terracotta", "minecraft:purple_glazed_terracotta",

    # Wool (all colors)
    "minecraft:white_wool", "minecraft:light_gray_wool",
    "minecraft:gray_wool", "minecraft:black_wool",
    "minecraft:red_wool", "minecraft:blue_wool",
    "minecraft:green_wool", "minecraft:yellow_wool",
    "minecraft:purple_wool", "minecraft:orange_wool",
    "minecraft:pink_wool", "minecraft:brown_wool",
    "minecraft:cyan_wool", "minecraft:magenta_wool",

    # Glass
    "minecraft:glass", "minecraft:tinted_glass",
    "minecraft:white_stained_glass", "minecraft:light_gray_stained_glass",
    "minecraft:gray_stained_glass", "minecraft:black_stained_glass",
    "minecraft:red_stained_glass", "minecraft:blue_stained_glass",
    "minecraft:cyan_stained_glass", "minecraft:purple_stained_glass",
    "minecraft:orange_stained_glass", "minecraft:yellow_stained_glass",
    "minecraft:glass_pane", "minecraft:iron_bars",

    # Nature / organic
    "minecraft:grass_block", "minecraft:dirt", "minecraft:coarse_dirt",
    "minecraft:podzol", "minecraft:mycelium", "minecraft:mud",
    "minecraft:packed_mud", "minecraft:moss_block", "minecraft:moss_carpet",
    "minecraft:clay", "minecraft:gravel", "minecraft:sand", "minecraft:red_sand",
    "minecraft:snow_block", "minecraft:packed_ice", "minecraft:blue_ice",
    "minecraft:ice", "minecraft:dripstone_block",

    # Sculk
    "minecraft:sculk", "minecraft:sculk_catalyst", "minecraft:sculk_vein",

    # Furniture / decoration
    "minecraft:bookshelf", "minecraft:chiseled_bookshelf",
    "minecraft:spawner", "minecraft:chest",
    "minecraft:trapped_chest", "minecraft:barrel", "minecraft:ender_chest",
    "minecraft:furnace", "minecraft:blast_furnace", "minecraft:smoker",
    "minecraft:anvil", "minecraft:chipped_anvil", "minecraft:damaged_anvil",
    "minecraft:grindstone", "minecraft:smithing_table", "minecraft:fletching_table",
    "minecraft:cartography_table", "minecraft:loom",
    "minecraft:brewing_stand", "minecraft:cauldron",
    "minecraft:enchanting_table", "minecraft:lectern",
    "minecraft:cobweb", "minecraft:chain",
    "minecraft:flower_pot", "minecraft:armor_stand",
    "minecraft:bell", "minecraft:campfire", "minecraft:soul_campfire",
    "minecraft:fire", "minecraft:soul_fire",
    "minecraft:hay_block", "minecraft:target", "minecraft:lodestone",
    "minecraft:respawn_anchor", "minecraft:conduit",
    "minecraft:skeleton_skull", "minecraft:wither_skeleton_skull",
    "minecraft:zombie_head", "minecraft:creeper_head",
    "minecraft:dragon_head",
    "minecraft:jack_o_lantern", "minecraft:carved_pumpkin",

    # Lighting
    "minecraft:lantern", "minecraft:soul_lantern",
    "minecraft:torch", "minecraft:soul_torch",
    "minecraft:redstone_torch", "minecraft:redstone_lamp",
    "minecraft:candle", "minecraft:end_rod",

    # Redstone / traps
    "minecraft:lever", "minecraft:tripwire_hook", "minecraft:tnt",
    "minecraft:dispenser", "minecraft:dropper", "minecraft:hopper",
    "minecraft:piston", "minecraft:sticky_piston",
    "minecraft:observer", "minecraft:daylight_detector",
    "minecraft:note_block", "minecraft:jukebox",
    "minecraft:stone_pressure_plate", "minecraft:oak_pressure_plate",
    "minecraft:stone_button", "minecraft:oak_button",
    "minecraft:iron_trapdoor", "minecraft:oak_trapdoor",
    "minecraft:iron_door", "minecraft:oak_door",

    # Miscellaneous
    "minecraft:bone_block", "minecraft:dried_kelp_block",
    "minecraft:honeycomb_block", "minecraft:slime_block",
    "minecraft:honey_block", "minecraft:sponge", "minecraft:wet_sponge",
    "minecraft:melon", "minecraft:pumpkin",
    "minecraft:bamboo_block", "minecraft:bamboo_mosaic",
    "minecraft:tuff", "minecraft:tuff_bricks", "minecraft:polished_tuff",
    "minecraft:calcite", "minecraft:diorite", "minecraft:polished_diorite",
    "minecraft:granite", "minecraft:polished_granite",
    "minecraft:andesite", "minecraft:polished_andesite",

    # Water / lava (for details)
    "minecraft:water", "minecraft:lava",

    # Special
    "minecraft:air",
}

# ---------------------------------------------------------------------------
# Entities (~30+)
# ---------------------------------------------------------------------------
VALID_ENTITY_IDS: set[str] = {
    # Undead
    "minecraft:zombie", "minecraft:skeleton", "minecraft:husk",
    "minecraft:stray", "minecraft:drowned", "minecraft:phantom",
    "minecraft:zombie_villager", "minecraft:wither_skeleton",
    "minecraft:skeleton_horse",

    # Arthropods
    "minecraft:spider", "minecraft:cave_spider",
    "minecraft:silverfish", "minecraft:endermite",

    # Hostile
    "minecraft:creeper", "minecraft:witch", "minecraft:enderman",
    "minecraft:blaze", "minecraft:ghast", "minecraft:magma_cube",
    "minecraft:slime", "minecraft:shulker",
    "minecraft:guardian", "minecraft:elder_guardian",
    "minecraft:hoglin", "minecraft:piglin", "minecraft:piglin_brute",
    "minecraft:warden",

    # Illagers
    "minecraft:pillager", "minecraft:vindicator", "minecraft:evoker",
    "minecraft:ravager", "minecraft:vex",

    # Neutral (can be hostile)
    "minecraft:bee", "minecraft:iron_golem",
    "minecraft:wolf", "minecraft:polar_bear",

    # Passive (for decoration / ambiance)
    "minecraft:bat", "minecraft:cat", "minecraft:villager",
    "minecraft:armor_stand",
}

# ---------------------------------------------------------------------------
# Items (~60+)
# ---------------------------------------------------------------------------
VALID_ITEM_IDS: set[str] = {
    # Swords
    "minecraft:wooden_sword", "minecraft:stone_sword",
    "minecraft:iron_sword", "minecraft:golden_sword",
    "minecraft:diamond_sword", "minecraft:netherite_sword",

    # Pickaxes
    "minecraft:wooden_pickaxe", "minecraft:stone_pickaxe",
    "minecraft:iron_pickaxe", "minecraft:golden_pickaxe",
    "minecraft:diamond_pickaxe", "minecraft:netherite_pickaxe",

    # Axes
    "minecraft:iron_axe", "minecraft:diamond_axe", "minecraft:netherite_axe",

    # Bows / ranged
    "minecraft:bow", "minecraft:crossbow", "minecraft:trident",
    "minecraft:arrow", "minecraft:spectral_arrow", "minecraft:tipped_arrow",

    # Armor
    "minecraft:leather_helmet", "minecraft:leather_chestplate",
    "minecraft:leather_leggings", "minecraft:leather_boots",
    "minecraft:chainmail_helmet", "minecraft:chainmail_chestplate",
    "minecraft:chainmail_leggings", "minecraft:chainmail_boots",
    "minecraft:iron_helmet", "minecraft:iron_chestplate",
    "minecraft:iron_leggings", "minecraft:iron_boots",
    "minecraft:diamond_helmet", "minecraft:diamond_chestplate",
    "minecraft:diamond_leggings", "minecraft:diamond_boots",
    "minecraft:netherite_helmet", "minecraft:netherite_chestplate",
    "minecraft:netherite_leggings", "minecraft:netherite_boots",

    # Shields / utility
    "minecraft:shield", "minecraft:totem_of_undying",
    "minecraft:elytra", "minecraft:spyglass",

    # Food / consumables
    "minecraft:golden_apple", "minecraft:enchanted_golden_apple",
    "minecraft:bread", "minecraft:cooked_beef", "minecraft:cooked_porkchop",
    "minecraft:golden_carrot", "minecraft:cookie", "minecraft:cake",
    "minecraft:pumpkin_pie", "minecraft:rabbit_stew",
    "minecraft:potion", "minecraft:splash_potion", "minecraft:lingering_potion",

    # Ender / magic
    "minecraft:ender_pearl", "minecraft:ender_eye",
    "minecraft:experience_bottle", "minecraft:book",
    "minecraft:enchanted_book", "minecraft:name_tag",

    # Misc tools
    "minecraft:compass", "minecraft:recovery_compass",
    "minecraft:clock", "minecraft:map", "minecraft:saddle",
    "minecraft:lead", "minecraft:fishing_rod",
    "minecraft:flint_and_steel", "minecraft:shears",
    "minecraft:bucket", "minecraft:water_bucket", "minecraft:lava_bucket",
    "minecraft:torch", "minecraft:soul_torch",

    # Raw materials
    "minecraft:diamond", "minecraft:emerald",
    "minecraft:iron_ingot", "minecraft:gold_ingot",
    "minecraft:copper_ingot", "minecraft:netherite_ingot",
    "minecraft:netherite_scrap",
    "minecraft:redstone", "minecraft:lapis_lazuli",
    "minecraft:quartz", "minecraft:amethyst_shard",
    "minecraft:echo_shard", "minecraft:nether_star",
    "minecraft:coal", "minecraft:charcoal",
    "minecraft:bone", "minecraft:blaze_rod", "minecraft:blaze_powder",
    "minecraft:ghast_tear", "minecraft:phantom_membrane",
    "minecraft:gunpowder", "minecraft:string",
    "minecraft:slime_ball", "minecraft:magma_cream",

    # Mob drops (AI loves these for loot)
    "minecraft:rotten_flesh", "minecraft:spider_eye",
    "minecraft:ender_eye", "minecraft:rabbit_foot",
    "minecraft:leather", "minecraft:feather",
    "minecraft:flint", "minecraft:stick",
    "minecraft:iron_nugget", "minecraft:gold_nugget",
    "minecraft:prismarine_shard", "minecraft:prismarine_crystals",
    "minecraft:nautilus_shell", "minecraft:heart_of_the_sea",
    "minecraft:wither_skeleton_skull",
    "minecraft:dragon_breath", "minecraft:shulker_shell",

    # Music discs
    "minecraft:music_disc_13", "minecraft:music_disc_cat",
    "minecraft:music_disc_pigstep", "minecraft:music_disc_otherside",
}
