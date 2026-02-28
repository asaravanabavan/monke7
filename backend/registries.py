"""
Hardcoded sets of valid Minecraft 1.20.1 IDs for NemoCraft.

Covers stone dungeon, nether fortress, and ocean monument palettes,
plus common furniture/decoration blocks, hostile mobs, and loot items.
"""

# ---------------------------------------------------------------------------
# Blocks (~60)
# ---------------------------------------------------------------------------
VALID_BLOCK_IDS: set[str] = {
    # Stone dungeon palette
    "minecraft:stone",
    "minecraft:cobblestone",
    "minecraft:mossy_cobblestone",
    "minecraft:stone_bricks",
    "minecraft:mossy_stone_bricks",
    "minecraft:cracked_stone_bricks",
    "minecraft:chiseled_stone_bricks",
    # Deepslate palette
    "minecraft:deepslate",
    "minecraft:deepslate_bricks",
    "minecraft:cobbled_deepslate",
    "minecraft:polished_deepslate",
    "minecraft:deepslate_tiles",
    # Nether fortress palette
    "minecraft:nether_bricks",
    "minecraft:red_nether_bricks",
    "minecraft:soul_sand",
    "minecraft:soul_soil",
    "minecraft:netherrack",
    "minecraft:basalt",
    "minecraft:polished_basalt",
    "minecraft:blackstone",
    "minecraft:polished_blackstone",
    "minecraft:polished_blackstone_bricks",
    "minecraft:gilded_blackstone",
    "minecraft:magma_block",
    "minecraft:glowstone",
    "minecraft:shroomlight",
    # Ocean monument palette
    "minecraft:prismarine",
    "minecraft:dark_prismarine",
    "minecraft:prismarine_bricks",
    "minecraft:sea_lantern",
    # Obsidian / End palette
    "minecraft:obsidian",
    "minecraft:crying_obsidian",
    "minecraft:end_stone",
    "minecraft:end_stone_bricks",
    "minecraft:purpur_block",
    "minecraft:purpur_pillar",
    # Wood planks
    "minecraft:oak_planks",
    "minecraft:spruce_planks",
    "minecraft:dark_oak_planks",
    # Metal / ore blocks
    "minecraft:iron_block",
    "minecraft:gold_block",
    "minecraft:redstone_block",
    "minecraft:lapis_block",
    "minecraft:emerald_block",
    "minecraft:diamond_block",
    # Furniture / decoration
    "minecraft:bookshelf",
    "minecraft:spawner",
    "minecraft:chest",
    "minecraft:barrel",
    "minecraft:furnace",
    "minecraft:anvil",
    "minecraft:grindstone",
    "minecraft:brewing_stand",
    "minecraft:cauldron",
    "minecraft:cobweb",
    "minecraft:iron_bars",
    "minecraft:chain",
    # Lighting
    "minecraft:lantern",
    "minecraft:soul_lantern",
    "minecraft:torch",
    "minecraft:soul_torch",
    "minecraft:redstone_torch",
    # Redstone / traps
    "minecraft:lever",
    "minecraft:tripwire_hook",
    "minecraft:tnt",
    # Special
    "minecraft:air",
}

# ---------------------------------------------------------------------------
# Entities (~15)
# ---------------------------------------------------------------------------
VALID_ENTITY_IDS: set[str] = {
    "minecraft:zombie",
    "minecraft:skeleton",
    "minecraft:spider",
    "minecraft:cave_spider",
    "minecraft:creeper",
    "minecraft:witch",
    "minecraft:enderman",
    "minecraft:blaze",
    "minecraft:wither_skeleton",
    "minecraft:stray",
    "minecraft:husk",
    "minecraft:drowned",
    "minecraft:phantom",
    "minecraft:pillager",
    "minecraft:vindicator",
}

# ---------------------------------------------------------------------------
# Items (~30+)
# ---------------------------------------------------------------------------
VALID_ITEM_IDS: set[str] = {
    # Weapons
    "minecraft:diamond_sword",
    "minecraft:iron_sword",
    "minecraft:golden_sword",
    "minecraft:diamond_pickaxe",
    "minecraft:iron_pickaxe",
    "minecraft:bow",
    "minecraft:crossbow",
    "minecraft:arrow",
    "minecraft:spectral_arrow",
    "minecraft:shield",
    # Armour
    "minecraft:diamond_chestplate",
    "minecraft:iron_chestplate",
    # Food / consumables
    "minecraft:golden_apple",
    "minecraft:enchanted_golden_apple",
    "minecraft:ender_pearl",
    "minecraft:experience_bottle",
    "minecraft:totem_of_undying",
    "minecraft:potion",
    "minecraft:splash_potion",
    "minecraft:bread",
    "minecraft:cooked_beef",
    "minecraft:golden_carrot",
    # Miscellaneous
    "minecraft:book",
    "minecraft:compass",
    "minecraft:map",
    "minecraft:name_tag",
    "minecraft:saddle",
    # Raw materials
    "minecraft:diamond",
    "minecraft:emerald",
    "minecraft:iron_ingot",
    "minecraft:gold_ingot",
    "minecraft:redstone",
    "minecraft:lapis_lazuli",
}
