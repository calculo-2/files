"""Catálogo completo de objetos interativos do Genshin Impact (PT-BR e Inglês).

Organiza todos os objetos rastreáveis no mapa interativo (appsample e banco local):
1. Permanentes (ligados por padrão — contam para 100% de exploração/progresso):
   - Baús (Comum, Sofisticado, Precioso, Luxuoso, Estranho / Remarkable)
   - Santuários das Profundezas (todas as nações)
   - Oculi (Anemo, Geo, Electro, Dendro, Hydro, Pyro, Cryo, Lunoculus)
   - Oferendas e coletáveis regionais (Calcedônia Carmesim, Espato Lúmen, Lanterna Lúmen,
     Carpa Espiritual, Pluma da Luz Purificadora, Selo Sagrado, Padrão de Chave I–V,
     Pérola da Lua Antiga, Kuuhenki, Orvalho Kuuvahki, Cristal Kresnik, Gotas de Asas
     Sombrias, Conjuntos Mnemônicos)
   - Pontos de navegação e desbloqueio (Ponto de Teleporte, Estação de Alta Velocidade,
     Ancoragem do Quebra-mar, Estátua dos Sete, Domínio, Observatório)
   - Guias, desafios e enigmas (Seelie Guia, Seelie Electro, Monetoo, Desafios Contra o
     Tempo, Desafio do Guerreiro, Desafio do Totem, Baú Enterrado, Monumento Elemental,
     Quebra-Cabeça de Tocha, Pilhas de Pedras, Baú Selado, Mini Quebra-Cabeças e todas as
     ~95 subcategorias de "Baú de Enigma" do appsample)
   - Caixas de Mora, Pilhas de Pedra/Areia e Selos Geo na parede
   - Coleção permanente (Cristal Rodopiante Radiante, Receitas, Livros/Textos/Tabuletas,
     Lendas Locais, Hilichurl Estranho, Aranara)
2. Respawnáveis / Farmáveis (opcionais via `detect.include_respawnables = true`):
   - Todas as 64+ Especialidades Locais (Mondstadt a Snezhnaya / Lua Gelada)
   - Todos os 9 Minérios
   - Pontos de Pesca e Pontos de Investigação de Artefatos
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectSpec:
    kind: str
    # chest, shrine, oculus, offering, waypoint, puzzle, mora, collectable, specialty,
    # mineral, guide
    group: str
    label_pt: str
    permanent: bool = True
    site_titles_pt: tuple[str, ...] = ()
    site_titles_en: tuple[str, ...] = ()
    ocr_keywords: tuple[str, ...] = ()
    default_type_ids: tuple[str, ...] = ()
    radius_factor: float = 1.0  # multiplicador sobre o raio base de busca
    cooldown: float = 6.0  # intervalo mínimo entre eventos iguais (s)

    @property
    def all_site_titles(self) -> tuple[str, ...]:
        return self.site_titles_pt + self.site_titles_en


# Todas as subcategorias de "Baú de Enigma" (Puzzle Chest) do appsample em PT-BR e EN.
# No appsample, baús que nascem de puzzles/desafios/guias ficam nestas categorias
# e NÃO em "Baú Comum".
PUZZLE_CHEST_TITLES_PT: tuple[str, ...] = (
    "Seelie Guia",
    "Seelie Guia Electro",
    "Monetoo",
    "Desafios Contra o Tempo",
    "Desafio do Guerreiro",
    "Desafio do Totem",
    "Mecanismo do Moinho de Vento",
    "Slimes Anemo Flutuantes",
    "Mecanismo de Pressão",
    "Sementes Flutuantes",
    "Baú Enterrado",
    "Enterrado",
    "Monumento Elemental",
    "Quebra-Cabeça de Tocha",
    "Pilha de Pedras Grande",
    "Pilha de Pedras Pequena",
    "Plantas a Colher",
    "Baú Selado",
    "Geogrão",
    "Mini Quebra-Cabeças",
    "Primeiro Inimigo Eliminado",
    "Barreira de Vento",
    "Gelo Ancestral",
    "Mecanismo Cúbico",
    "Garoto Kujirai",
    "Dandy",
    "Condução Elétrica",
    "Placas de conexão",
    "Sonda do Golpe do Relâmpago",
    "Empunhadura da Espada",
    "Fantasma",
    "Pedra Estranha",
    "O Definhamento",
    "Enigmas de Sumeru",
    "Sementeira na Selva",
    "Selo no Pilar de Pedra",
    "Portal Onírico",
    "Máquina Saghira",
    "Sementes Tri-Yana",
    "Obelisco Primordial",
    "Mural Fantasma",
    "Células da Luz Eterna",
    "Brasa Primordial",
    "Ampulheta Primordial",
    "Monstro dentro do Cristal Cinza",
    "Obelisco Erodido",
    "Espírito Anemo do Presságio",
    "Depósito de Água",
    "Efemérida Amrita",
    "Cristal Cinza",
    "Flor Sunyata",
    "Tambor Kory",
    "Fruta Nirodha",
    "Sino das Almas",
    "Árvore Fravashi",
    "Efemérida Khvarena",
    "Pavio Farr",
    "Espírito Florescente",
    "Mecanismo de Pneuma-ousia",
    "Aeronave",
    "Terminal de Transferência de Energia",
    "Estabilizador",
    "Fruta da Água",
    "Cano de Algas Harmoniosas",
    "Orbe de Energia Potencial",
    "Mecanismo Operável",
    "Caldeirão de Incenso de Jade",
    "Ruínas antigas",
    "Cenas de Lótus Fluentes",
    "Simulacro Sagrado",
    "Ponto de Miasma",
    "Estante",
    "Flauta de Pã Auto-Harmônica",
    "Bola Relé",
    "Câmara do Julgamento da Noite",
    "Cabeça do... Ídolo Draconiano",
    "Pulveritas",
    "Fissura Geotermal",
    "Uma Audiência com o Pilar do Espírito da Noite",
    "Flormentado",
    "Núcleo Suspenso de Lama",
    "Pérola de Coagulação",
    "Kuuvahki",
    "Caminhos Lunares",
    "Módulos de Montagem",
    "Robô",
    "Pedra Sela-Maré",
    "Espelho da Lua",
    "Gerador de Barreira",
    "Toupeiras Cheiradeiras",
    "Robô de Limpeza",
    "Robôs de Reconhecimento",
    "Partículas da Lua",
    "Olho Maléfico da Praga",
    "Barreira da Confluência Lunar",
    "O Núcleo Estilhaçado da Barreira",
    "O Núcleo Solaris e o Caule Noturno",
    "Poder Abissal Transbordante",
    "Prisma",
    "Barreira de Névoa Abissal",
    "Energia Arqueolunar",
    "Constructo Glacial",
    "Diagrama de Constructo",
    "Baús Revelados pela Luz",
    "Flora de Cristal",
    "Pedestal de Foco Luminoso",
    "Mecanismo Triangular",
    "Lugar de Adoração de Essência",
)

PUZZLE_CHEST_TITLES_EN: tuple[str, ...] = (
    "Seelie",
    "Electro Seelie",
    "Monetoo",
    "Time Trial",
    "Warrior's Challenges",
    "Totem Challenge",
    "Windmill Mechanism",
    "Floating Anemo Slime",
    "Pressure Plate",
    "Bloatty Floatty",
    "Buried Chest",
    "Buried",
    "Elemental Monument",
    "Torch Puzzle",
    "Large Rock Pile",
    "Small Rock Pile",
    "Harvestable Plant",
    "Sealed Chest",
    "Geogranum",
    "Mini Puzzle",
    "Enemies (First-Time Victory)",
    "Storm Barrier",
    "Ancient Rime",
    "Cube Devices",
    "Kid Kujirai",
    "Electric Conduction",
    "Light-Up Tile Puzzle",
    "Lightning Strike Probe",
    "Sword Hilt",
    "Illusion",
    "Unique Rocks",
    "The Withering",
    "Sumeru Puzzles",
    "Nurseries in the Wilds",
    "Stone Pillar Seal",
    "Phantasmal Gate",
    "Saghira Machine",
    "Tri-Yana Seeds",
    "Primal Obelisk",
    "Illusion Mural",
    "Everlight Cell",
    "Primal Ember",
    "Primal Sandglass",
    "Weathered Obelisk",
    "Signal Spirit",
    "Cascade Pools",
    "Amrita Mayfly",
    "Sunyata Flower",
    "Kory Drum",
    "Nirodha Fruit",
    "Soul Bell",
    "Fravashi Tree",
    "Khvarena Mayfly",
    "Farrwick",
    "Burgeoning Spirit",
    "Pneumousia Mechanism",
    "Energy Transfer Terminal",
    "Stabilizer",
    "Jadewater Fruit",
    "Harmonious Reed Pipe",
    "Potential Energy Orbs",
    "Operable Mechanism",
    "Jade Incense Cauldron",
    "Ancient Ruins",
    "Scenes of Flowing Lotuses",
    "Carefree Simulacrum",
    "Miasma Location",
    "Bookcase",
    "Autoharmonic Reed Pipes",
    "Relay Ball",
    "Place of the Trial of Disembodiment",
    "Pulverite",
    "Geothermal Vent",
    "An Audience With the Nightsoul Pillar",
    "Brewblossoms",
    "Moonlanes",
    "Assembly Modules",
    "Tideseal Stones",
    "The Moon Mirror",
    "Barrier Generator",
    "Sniffer Mole",
    "Cleaning Bots",
    "Recon Bots",
    "Moonlit Particles",
    "The Evil Eye of Blightseep",
    "Lunar Conflux Barrier",
    "The Shattered Barrier Core",
    "The Solaris Core and Nycalyx",
    "Overflowing Abyssal Power",
    "Prism",
    "Abyssal Fog Barriers",
    "Archaeolune Energy",
    "Prime Ice Construct",
    "Construct Blueprint",
    "Light-Revealed Chests",
    "Crystal Flora",
    "Light-Focusing Pedestal",
)

MORA_CHEST_TITLES_PT: tuple[str, ...] = (
    "Baú de Mora de Madeira",
    "Baú de Mora de Pilha de Pedras",
    "Baú de Mora de Pedra Destruída",
    "Baú de Mora de Fontaine",
    "Baú de Mora de Natlan",
    "Baús de Mora de Nod-Krai",
    "Baú de Mora de Lua Gelada",
    "Baús de Mora de Snezhnaya",
    "Selo Geo",
    "Pilhas de Areia",
    "Tesouros Ocultos",
    "Cofre dos tesouros do Reino das Sombras",
    "Mora",
)

MORA_CHEST_TITLES_EN: tuple[str, ...] = (
    "Wooden Mora Chest",
    "Stone Pile Mora Chest",
    "Gravel Mora Chest",
    "Fontaine Mora Chest",
    "Natlan Mora Chest",
    "Nod-Krai Mora Chest",
    "Frost Moon Mora Chest",
    "Snezhnaya Mora Chest",
    "Geo Sigil",
    "Sand Pile",
    "Hidden Troves",
    "Shadow Realm Treasure Vault",
)

# (slug, PT-BR no site/jogo, Inglês no site/jogo, apelidos extras de OCR)
LOCAL_SPECIALTIES_DATA: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    # Mondstadt
    ("valberry", "Valberry", "Valberry", ("baga valberry",)),
    ("calla_lily", "Lótus de Leite", "Calla Lily", ("lirio calla",)),
    ("small_lamp_grass", "Lâmpada de Grama", "Small Lamp Grass", ("grama do pequeno lampiao",)),
    ("cecilia", "Cecília", "Cecilia", ()),
    ("dandelion_seed", "Sementes de Dandelion", "Dandelion Seed", ("semente de dandelion",)),
    ("philanemo_mushroom", "Cogumelo Philanemo", "Philanemo Mushroom", ()),
    ("wolfhook", "Gancho do Lobo", "Wolfhook", ()),
    ("windwheel_aster", "Margarida Voadora", "Windwheel Aster", ()),
    # Liyue & Vale Chenyu & Despenhadeiro
    ("jueyun_chili", "Pimenta de Jueyun", "Jueyun Chili", ()),
    ("qingxin", "Qingxin", "Qingxin", ()),
    ("violetgrass", "Violeta", "Violetgrass", ("campanula violeta",)),
    ("silk_flower", "Flor de Seda", "Silk Flower", ()),
    ("glaze_lily", "Vidro de Lily", "Glaze Lily", ("lirio de vidro",)),
    ("cor_lapis", "Cor Lapis", "Cor Lapis", ()),
    ("noctilucous_jade", "Jade Nocticuloso", "Noctilucous Jade", ()),
    ("starconch", "Concha Estrelada", "Starconch", ()),
    ("clearwater_jade", "Jade Cristalino", "Clearwater Jade", ()),
    # Inazuma & Enkanomiya
    ("sea_ganoderma", "Fungos Marítimos", "Sea Ganoderma", ("fungo maritimo",)),
    ("onikabuto", "Onikabuto", "Onikabuto", ()),
    ("naku_weed", "Erva Naku", "Naku Weed", ()),
    ("dendrobium", "Dendróbio", "Dendrobium", ()),
    ("sakura_bloom", "Flor Sakura", "Sakura Bloom", ("petala de sakura",)),
    ("crystal_marrow", "Medula de Cristal", "Crystal Marrow", ()),
    ("sango_pearl", "Pérola Sango", "Sango Pearl", ()),
    ("amakumo_fruit", "Fruto Tenkumo", "Amakumo Fruit", ("fruto amakumo",)),
    ("fluorescent_fungus", "Fungos Fluorescentes", "Fluorescent Fungus", ("fungo fluorescente",)),
    # Sumeru
    ("nilotpala_lotus", "Lótus Nilotpala", "Nilotpala Lotus", ()),
    ("kalpalata_lotus", "Lótus Kalpalata", "Kalpalata Lotus", ()),
    ("rukkhashava_mushroom", "Cogumelo Rukkhashava", "Rukkhashava Mushroom", ()),
    ("padisarah", "Padisarahs", "Padisarah", ("padisarah",)),
    ("scarab", "Escaravelho Dourado", "Scarab", ()),
    ("henna_berry", "Bagas de Espinheiro", "Henna Berry", ("baga de espinheiro", "fruto vermelho")),
    ("sand_grease_pupa", "Gordura de Pupa de Areia", "Sand Grease Pupa", ("pupa de areia",)),
    ("trishiraite", "Trishiraita", "Trishiraite", ()),
    ("mourning_flower", "Flor do Luto", "Mourning Flower", ()),
    # Fontaine & Mar Antigo
    ("beryl_conch", "Concha de Cristal Azul", "Beryl Conch", ("concha berilo",)),
    ("romaritime_flower", "Flor Rociomarinha", "Romaritime Flower", ()),
    ("lumidouce_bell", "Campânula Lumidouce", "Lumidouce Bell", ()),
    ("rainbow_rose", "Rosa Arco-Íris", "Rainbow Rose", ()),
    ("lumitoile", "Lumitoile", "Lumitoile", ()),
    ("subdetection_unit", "Unidade de Subdetecção", "Subdetection Unit", ()),
    ("lakelight_lily", "Flor da Luz do Lago", "Lakelight Lily", ()),
    ("spring_first_dewdrop", "Primavera do Primeiro Orvalho", "Spring of the First Dewdrop", ()),
    # Natlan
    ("sprayfeather_gill", "Guelra da Espuma", "Sprayfeather Gill", ()),
    ("saurian_claw_succulent", "Suculenta de Garra Sauriana", "Saurian Claw Succulent", ()),
    ("quenepa_berry", "Baga Quenepa", "Quenepa Berry", ()),
    ("brilliant_chrysanthemum", "Crisântemo Brilhante", "Brilliant Chrysanthemum", ()),
    ("withering_purpurbloom", "Flor Púrpura Definhada", "Withering Purpurbloom", ()),
    ("glowing_hornshroom", "Cogumelo Brilhante", "Glowing Hornshroom", ()),
    ("skysplit_gembloom", "Florgema Celeste", "Skysplit Gembloom", ()),
    ("dracolite", "Dracolita", "Dracolite", ()),
    # Nod-Krai, Lua Gelada & Snezhnaya
    ("portable_bearing", "Rolamento Portátil", "Portable Bearing", ()),
    ("frostlamp_flower", "Flor da Geada", "Frostlamp Flower", ()),
    ("moonfall_silver", "Prata Lunar", "Moonfall Silver", ()),
    ("winter_icelea", "Capim de Gelo Invernal", "Winter Icelea", ()),
    ("pine_amber", "Âmbar de Pinheiro", "Pine Amber", ()),
    ("etherwing_moth", "Mariposa Etérea", "Etherwing Moth", ()),
    ("frostfairy_flower", "Flor Imortal Gélida", "Frostfairy Flower", ()),
    ("flockingweed", "Ervaglomerada", "Flockingweed", ()),
    ("golden_fern", "Samambaia Dourada", "Golden Fern", ()),
    ("fairy_wormwood", "Absinto Feérico", "Fairy Wormwood", ()),
    ("kristallfold", "Cogumelo de Lamelas Cristalinas", "Kristallfold", ()),
    ("moon_tear", "Lágrima da Lua", "Moon Tear", ()),
)

MINERALS_DATA: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("mineral_white_iron", "Pedaço de Ferro Branco", "White Iron Chunk", ()),
    ("mineral_crystal", "Pedaço de Cristal", "Crystal Chunk", ()),
    ("mineral_magical_crystal", "Pedaço de Cristal Mágico", "Magical Crystal Chunk", ()),
    ("mineral_starsilver", "Minério de Prata Estrelada", "Starsilver", ()),
    ("mineral_scarlet_quartz", "Cristal de Sangue", "Scarlet Quartz", ("quartzo escarlate",)),
    ("mineral_iron", "Pedaço de ferro", "Iron Chunk", ("pedaco de ferro",)),
    ("mineral_amethyst", "Pedaço de Ametista", "Amethyst Lump", ()),
    ("mineral_condessence", "Cristal da Essência Condensada", "Condessence Crystal", ()),
    ("mineral_rainbowdrop", "Pingo de Arco-Íris", "Rainbowdrop Crystal", ()),
)


CORE_SPECS: tuple[ObjectSpec, ...] = (
    # --- Baús e Santuários ---
    ObjectSpec(
        kind="chest",
        group="chest",
        label_pt="baú",
        permanent=True,
        site_titles_pt=(
            "Baú Comum",
            "Baú Sofisticado",
            "Baú Precioso",
            "Baú Luxuoso",
            "Baú Estranho",
            "Santuário das Profundezas",
        ),
        site_titles_en=(
            "Common Chest",
            "Exquisite Chest",
            "Precious Chest",
            "Luxurious Chest",
            "Remarkable Chest",
            "Shrine of Depths",
        ),
        default_type_ids=("o17", "o44", "o45", "o46", "o269", "o8"),
        cooldown=15.0,
    ),
    ObjectSpec(
        kind="chest_common",
        group="chest",
        label_pt="baú comum",
        permanent=True,
        site_titles_pt=("Baú Comum",),
        site_titles_en=("Common Chest",),
        default_type_ids=("o17",),
        cooldown=15.0,
    ),
    ObjectSpec(
        kind="chest_exquisite",
        group="chest",
        label_pt="baú sofisticado",
        permanent=True,
        site_titles_pt=("Baú Sofisticado",),
        site_titles_en=("Exquisite Chest",),
        default_type_ids=("o44",),
        cooldown=15.0,
    ),
    ObjectSpec(
        kind="chest_precious",
        group="chest",
        label_pt="baú precioso",
        permanent=True,
        site_titles_pt=("Baú Precioso",),
        site_titles_en=("Precious Chest",),
        default_type_ids=("o45",),
        cooldown=15.0,
    ),
    ObjectSpec(
        kind="chest_luxurious",
        group="chest",
        label_pt="baú luxuoso",
        permanent=True,
        site_titles_pt=("Baú Luxuoso",),
        site_titles_en=("Luxurious Chest",),
        default_type_ids=("o46",),
        cooldown=15.0,
    ),
    ObjectSpec(
        kind="remarkable_chest",
        group="chest",
        label_pt="baú estranho",
        permanent=True,
        site_titles_pt=("Baú Estranho",),
        site_titles_en=("Remarkable Chest",),
        default_type_ids=("o269",),
        cooldown=15.0,
    ),
    ObjectSpec(
        kind="shrine",
        group="shrine",
        label_pt="santuário das profundezas",
        permanent=True,
        site_titles_pt=("Santuário das Profundezas",),
        site_titles_en=("Shrine of Depths",),
        default_type_ids=("o8",),
        cooldown=15.0,
    ),
    # --- Oculi (8 regiões) ---
    ObjectSpec(
        kind="anemoculus",
        group="oculus",
        label_pt="anemoculus",
        site_titles_pt=("Anemoculus",),
        site_titles_en=("Anemoculus",),
        ocr_keywords=("anemoculus", "anemoculo"),
        default_type_ids=("o5",),
    ),
    ObjectSpec(
        kind="geoculus",
        group="oculus",
        label_pt="geoculus",
        site_titles_pt=("Geoculus",),
        site_titles_en=("Geoculus",),
        ocr_keywords=("geoculus", "geoculo"),
        default_type_ids=("o6",),
    ),
    ObjectSpec(
        kind="electroculus",
        group="oculus",
        label_pt="electroculus",
        site_titles_pt=("Electroculus",),
        site_titles_en=("Electroculus",),
        ocr_keywords=("electroculus", "electroculo", "eletroculo", "eletroculus"),
        default_type_ids=("o194",),
    ),
    ObjectSpec(
        kind="dendroculus",
        group="oculus",
        label_pt="dendroculus",
        site_titles_pt=("Dendroculus",),
        site_titles_en=("Dendroculus",),
        ocr_keywords=("dendroculus", "dendroculo"),
        default_type_ids=("o403",),
    ),
    ObjectSpec(
        kind="hydroculus",
        group="oculus",
        label_pt="hydroculus",
        site_titles_pt=("Hydroculus",),
        site_titles_en=("Hydroculus",),
        ocr_keywords=("hydroculus", "hidroculo", "hydroculo", "hidroculus"),
        default_type_ids=("o508",),
    ),
    ObjectSpec(
        kind="pyroculus",
        group="oculus",
        label_pt="pyroculus",
        site_titles_pt=("Pyroculus",),
        site_titles_en=("Pyroculus",),
        ocr_keywords=("pyroculus", "piroculo", "pyroculo", "piroculus"),
        default_type_ids=("o626",),
    ),
    ObjectSpec(
        kind="cryoculus",
        group="oculus",
        label_pt="cryoculus",
        site_titles_pt=("Cryoculus",),
        site_titles_en=("Cryoculus",),
        ocr_keywords=("cryoculus", "crioculo", "cryoculo", "crioculus"),
        default_type_ids=("o833",),
    ),
    ObjectSpec(
        kind="lunoculus",
        group="oculus",
        label_pt="lunoculus",
        site_titles_pt=("Lunoculus",),
        site_titles_en=("Lunoculus",),
        ocr_keywords=("lunoculus", "lunoculo"),
        default_type_ids=("o694",),
    ),
    # --- Oferendas e Coletáveis Regionais de Exploração ---
    ObjectSpec(
        kind="crimson_agate",
        group="offering",
        label_pt="calcedônia carmesim",
        site_titles_pt=("Calcedônia Carmesim",),
        site_titles_en=("Crimson Agate",),
        ocr_keywords=("calcedonia carmesim", "agata carmesim", "crimson agate"),
    ),
    ObjectSpec(
        kind="lumenspar",
        group="offering",
        label_pt="espato lúmen",
        site_titles_pt=("Espato Lúmen",),
        site_titles_en=("Lumenspar",),
        ocr_keywords=("espato lumen", "minerio lumen", "lumenspar"),
    ),
    ObjectSpec(
        kind="lumenlamp",
        group="offering",
        label_pt="lanterna lúmen",
        site_titles_pt=("Lanterna Lúmen",),
        site_titles_en=("Lumenlamp",),
        ocr_keywords=("lanterna lumen", "lumenlamp"),
    ),
    ObjectSpec(
        kind="spirit_carp",
        group="offering",
        label_pt="carpa espiritual",
        site_titles_pt=("Carpas Espirituais", "Carpa Espiritual"),
        site_titles_en=("Spirit Carp",),
        ocr_keywords=("carpa espiritual", "carpas espirituais", "spirit carp"),
    ),
    ObjectSpec(
        kind="plume_of_light",
        group="offering",
        label_pt="pluma da luz purificadora",
        site_titles_pt=("Plumas da Luz Purificadora", "Pluma da Luz Purificadora"),
        site_titles_en=("Plume of Purifying Light",),
        ocr_keywords=(
            "pluma da luz purificadora",
            "plumas da luz purificadora",
            "plume of purifying light",
        ),
    ),
    ObjectSpec(
        kind="sacred_seal",
        group="offering",
        label_pt="selo sagrado",
        site_titles_pt=("Selo Sagrado",),
        site_titles_en=("Sacred Seal",),
        ocr_keywords=("selo sagrado", "sacred seal"),
    ),
    ObjectSpec(
        kind="key_sigil",
        group="offering",
        label_pt="padrão de chave",
        site_titles_pt=("Padrão de Chave",),
        site_titles_en=("Key Sigil",),
        ocr_keywords=("padrao de chave", "key sigil"),
    ),
    ObjectSpec(
        kind="ancient_moon_pearl",
        group="offering",
        label_pt="pérola da lua antiga",
        site_titles_pt=("Pérola da Lua Antiga",),
        site_titles_en=("Ancient Moon Pearl",),
        ocr_keywords=("perola da lua antiga", "ancient moon pearl"),
    ),
    ObjectSpec(
        kind="kuuhenki",
        group="offering",
        label_pt="kuuhenki",
        site_titles_pt=("Kuuhenki",),
        site_titles_en=("Kuuhenki",),
        ocr_keywords=("kuuhenki",),
        radius_factor=1.3,
    ),
    ObjectSpec(
        kind="kuuvahki_dewdrop",
        group="offering",
        label_pt="orvalho kuuvahki",
        site_titles_pt=("Orvalho Kuuvahki",),
        site_titles_en=("Kuuvahki Dewdrops",),
        ocr_keywords=("orvalho kuuvahki", "kuuvahki dewdrop"),
    ),
    ObjectSpec(
        kind="kresnik_kristall",
        group="offering",
        label_pt="cristal kresnik",
        site_titles_pt=("Cristal Kresnik",),
        site_titles_en=("Kresnik Kristall",),
        ocr_keywords=("cristal kresnik", "kresnik kristall"),
    ),
    ObjectSpec(
        kind="shadow_wingdrop",
        group="offering",
        label_pt="gota de asa sombria",
        site_titles_pt=("Gotas de Asas Sombrias",),
        site_titles_en=("Shadow Wingdrop",),
        ocr_keywords=("gotas de asas sombrias", "gota de asa sombria", "shadow wingdrop"),
    ),
    ObjectSpec(
        kind="mnemonic_set",
        group="offering",
        label_pt="conjunto mnemônico",
        site_titles_pt=("Conjuntos Mnemônicos",),
        site_titles_en=("Mnemonic",),
        ocr_keywords=("conjunto mnemonico", "conjuntos mnemonicos"),
    ),
    # --- Pontos de Navegação e Desbloqueios ---
    ObjectSpec(
        kind="teleport",
        group="waypoint",
        label_pt="ponto de teleporte",
        site_titles_pt=(
            "Ponto de Teleporte",
            "Estação de Transporte de Alta Velocidade",
            "Local de Ancoragem do Quebra-mar",
        ),
        site_titles_en=(
            "Teleport Waypoint",
            "High-Speed Transport Station",
            "Waverider Waypoint",
        ),
        default_type_ids=("o3",),
        radius_factor=0.85,
        cooldown=8.0,
    ),
    ObjectSpec(
        kind="statue",
        group="waypoint",
        label_pt="estátua dos sete",
        site_titles_pt=("Estátua dos Sete",),
        site_titles_en=("Statue of Seven", "Statue of The Seven"),
        default_type_ids=("o2",),
        radius_factor=0.9,
        cooldown=10.0,
    ),
    ObjectSpec(
        kind="domain",
        group="waypoint",
        label_pt="domínio",
        site_titles_pt=("Domínio",),
        site_titles_en=("Domain",),
        default_type_ids=("o47",),
        radius_factor=0.95,
        cooldown=10.0,
    ),
    ObjectSpec(
        kind="viewpoint",
        group="waypoint",
        label_pt="observatório",
        site_titles_pt=("Observatório",),
        site_titles_en=("Viewpoint",),
        radius_factor=0.9,
        cooldown=8.0,
    ),
    # --- Guias, Desafios e Enigmas ---
    ObjectSpec(
        kind="seelie",
        group="puzzle",
        label_pt="seelie guia",
        site_titles_pt=("Seelie Guia", "Jardim de Seelie"),
        site_titles_en=("Seelie", "Seelie Court"),
        radius_factor=1.6,
        cooldown=12.0,
    ),
    ObjectSpec(
        kind="electro_seelie",
        group="puzzle",
        label_pt="seelie electro",
        site_titles_pt=("Seelie Guia Electro",),
        site_titles_en=("Electro Seelie",),
        radius_factor=1.8,
        cooldown=12.0,
    ),
    ObjectSpec(
        kind="monetoo",
        group="puzzle",
        label_pt="monetoo",
        site_titles_pt=("Monetoo",),
        site_titles_en=("Monetoo",),
        radius_factor=1.6,
        cooldown=12.0,
    ),
    ObjectSpec(
        kind="time_trial",
        group="puzzle",
        label_pt="desafio contra o tempo",
        site_titles_pt=("Desafios Contra o Tempo",),
        site_titles_en=("Time Trial",),
        radius_factor=1.6,
        cooldown=12.0,
    ),
    ObjectSpec(
        kind="warrior_challenge",
        group="puzzle",
        label_pt="desafio do guerreiro",
        site_titles_pt=("Desafio do Guerreiro", "Desafio do Totem"),
        site_titles_en=("Warrior's Challenges", "Totem Challenge"),
        radius_factor=1.5,
        cooldown=12.0,
    ),
    ObjectSpec(
        kind="buried_chest",
        group="puzzle",
        label_pt="baú enterrado",
        site_titles_pt=("Baú Enterrado", "Enterrado"),
        site_titles_en=("Buried Chest", "Buried"),
        radius_factor=0.9,
        cooldown=12.0,
    ),
    ObjectSpec(
        kind="elemental_monument",
        group="puzzle",
        label_pt="monumento elemental",
        site_titles_pt=("Monumento Elemental",),
        site_titles_en=("Elemental Monument",),
        radius_factor=1.3,
        cooldown=12.0,
    ),
    ObjectSpec(
        kind="torch_puzzle",
        group="puzzle",
        label_pt="quebra-cabeça de tocha",
        site_titles_pt=(
            "Quebra-Cabeça de Tocha",
            "Fogueira/Tocha",
            "Braseiro da Ruína",
            "Tocha de Kresnik",
        ),
        site_titles_en=("Torch Puzzle", "Campfire/Torch", "Ruin Brazier", "Kresnik's Torch"),
        radius_factor=1.3,
        cooldown=12.0,
    ),
    ObjectSpec(
        kind="rock_pile",
        group="puzzle",
        label_pt="pilha de pedras",
        site_titles_pt=("Pilha de Pedras Grande", "Pilha de Pedras Pequena"),
        site_titles_en=("Large Rock Pile", "Small Rock Pile"),
        radius_factor=1.0,
        cooldown=10.0,
    ),
    ObjectSpec(
        kind="sealed_chest",
        group="puzzle",
        label_pt="baú selado",
        site_titles_pt=("Baú Selado", "Barreira de Vento", "Baús Revelados pela Luz"),
        site_titles_en=("Sealed Chest", "Storm Barrier", "Light-Revealed Chests"),
        radius_factor=1.1,
        cooldown=12.0,
    ),
    ObjectSpec(
        kind="mini_puzzle",
        group="puzzle",
        label_pt="mini quebra-cabeça",
        site_titles_pt=("Mini Quebra-Cabeças",),
        site_titles_en=("Mini Puzzle",),
        radius_factor=1.2,
        cooldown=12.0,
    ),
    ObjectSpec(
        kind="puzzle_chest",
        group="puzzle",
        label_pt="baú de enigma",
        site_titles_pt=PUZZLE_CHEST_TITLES_PT,
        site_titles_en=PUZZLE_CHEST_TITLES_EN,
        radius_factor=1.35,
        cooldown=12.0,
    ),
    # --- Caixas de Mora e Pilhas de Pedra/Areia ---
    ObjectSpec(
        kind="mora_chest",
        group="mora",
        label_pt="caixa de mora",
        site_titles_pt=MORA_CHEST_TITLES_PT,
        site_titles_en=MORA_CHEST_TITLES_EN,
        radius_factor=0.95,
        cooldown=8.0,
    ),
    # --- Colecionáveis Permanentes ---
    ObjectSpec(
        kind="spincrystal",
        group="collectable",
        label_pt="cristal rodopiante radiante",
        site_titles_pt=("Cristal Rodopiante Radiante",),
        site_titles_en=("Radiant Spincrystal",),
        ocr_keywords=("cristal rodopiante radiante", "radiant spincrystal"),
        cooldown=8.0,
    ),
    ObjectSpec(
        kind="recipe",
        group="collectable",
        label_pt="receita",
        site_titles_pt=("Receita",),
        site_titles_en=("Recipe",),
        cooldown=8.0,
    ),
    ObjectSpec(
        kind="book",
        group="collectable",
        label_pt="livro / inscrição",
        site_titles_pt=(
            "Livro",
            "Texto interativo",
            "Tabuleta de Pedra Misteriosa",
            "Pedra Antiga",
            "Inscrição Iridescente",
            "Fragmento das Inscrições",
            "Fragmento da Inscrição de Khvarena",
        ),
        site_titles_en=(
            "Book",
            "Interactive Text",
            "Mysterious Stone Slate",
            "Archaic Stone",
            "Iridescent Inscription",
            '"Engraving" Fragment',
            "Khvarena Inscription Fragment",
        ),
        cooldown=8.0,
    ),
    ObjectSpec(
        kind="local_legend",
        group="collectable",
        label_pt="lenda local",
        site_titles_pt=("Lenda Local",),
        site_titles_en=("Local Legend",),
        radius_factor=1.5,
        cooldown=20.0,
    ),
    ObjectSpec(
        kind="unusual_hilichurl",
        group="collectable",
        label_pt="hilichurl estranho",
        site_titles_pt=("Hilichurl Estranho",),
        site_titles_en=("Unusual Hilichurl",),
        cooldown=15.0,
    ),
    ObjectSpec(
        kind="aranara",
        group="collectable",
        label_pt="aranara",
        site_titles_pt=("Aranara",),
        site_titles_en=("Aranara",),
        cooldown=10.0,
    ),
    # --- Guias e Recursos Respawnáveis (opcionais) ---
    ObjectSpec(
        kind="fishing_spot",
        group="guide",
        label_pt="ponto de pesca",
        permanent=False,
        site_titles_pt=("Ponto de Pesca",),
        site_titles_en=("Fishing Point",),
        cooldown=15.0,
    ),
    ObjectSpec(
        kind="artifact_spot",
        group="guide",
        label_pt="ponto de artefato",
        permanent=False,
        site_titles_pt=("Artefato",),
        site_titles_en=("Artifact",),
        cooldown=6.0,
    ),
)

SPECIALTY_SPECS: tuple[ObjectSpec, ...] = tuple(
    ObjectSpec(
        kind=f"specialty_{slug}",
        group="specialty",
        label_pt=pt.lower(),
        permanent=False,
        site_titles_pt=(pt,),
        site_titles_en=(en,),
        ocr_keywords=tuple({pt.lower(), en.lower(), *aliases}),
        cooldown=3.5,
    )
    for slug, pt, en, aliases in LOCAL_SPECIALTIES_DATA
)

MINERAL_SPECS: tuple[ObjectSpec, ...] = tuple(
    ObjectSpec(
        kind=slug,
        group="mineral",
        label_pt=pt.lower(),
        permanent=False,
        site_titles_pt=(pt,),
        site_titles_en=(en,),
        ocr_keywords=tuple({pt.lower(), en.lower(), *aliases}),
        cooldown=3.5,
    )
    for slug, pt, en, aliases in MINERALS_DATA
)

ALL_SPECS: tuple[ObjectSpec, ...] = CORE_SPECS + SPECIALTY_SPECS + MINERAL_SPECS
CATALOG: dict[str, ObjectSpec] = {spec.kind: spec for spec in ALL_SPECS}

OCULUS_KINDS: tuple[str, ...] = tuple(s.kind for s in CORE_SPECS if s.group == "oculus")
OFFERING_KINDS: tuple[str, ...] = tuple(s.kind for s in CORE_SPECS if s.group == "offering")
WAYPOINT_KINDS: tuple[str, ...] = tuple(s.kind for s in CORE_SPECS if s.group == "waypoint")
PUZZLE_KINDS: tuple[str, ...] = tuple(s.kind for s in CORE_SPECS if s.group == "puzzle")
COLLECTABLE_KINDS: tuple[str, ...] = tuple(s.kind for s in CORE_SPECS if s.group == "collectable")
SPECIALTY_KINDS: tuple[str, ...] = tuple(s.kind for s in SPECIALTY_SPECS)
MINERAL_KINDS: tuple[str, ...] = tuple(s.kind for s in MINERAL_SPECS)
PERMANENT_KINDS: frozenset[str] = frozenset(s.kind for s in ALL_SPECS if s.permanent)
RESPAWNABLE_KINDS: frozenset[str] = frozenset(s.kind for s in ALL_SPECS if not s.permanent)

GROUP_KINDS: dict[str, tuple[str, ...]] = {
    "oculus": OCULUS_KINDS,
    "offering": OFFERING_KINDS,
    "waypoint": WAYPOINT_KINDS,
    "puzzle": PUZZLE_KINDS,
    "mora": ("mora_chest",),
    "collectable": COLLECTABLE_KINDS,
    "specialty": SPECIALTY_KINDS,
    "mineral": MINERAL_KINDS,
    "guide": ("fishing_spot", "artifact_spot"),
}


def label_for_kind(kind: str, subtype: str | None = None) -> str:
    """Nome amigável em PT-BR para logs e painel."""
    if subtype and subtype in CATALOG and subtype != "chest":
        return CATALOG[subtype].label_pt
    spec = CATALOG.get(kind)
    return spec.label_pt if spec else kind


def radius_factor_for(kind: str, context: str | None = None) -> float:
    """Multiplicador de raio adequado ao tipo ou contexto da coleta."""
    if context and context in CATALOG:
        return max(
            CATALOG[context].radius_factor,
            CATALOG.get(kind, ObjectSpec(kind, "", kind)).radius_factor,
        )
    spec = CATALOG.get(kind)
    return spec.radius_factor if spec else 1.0


def cooldown_for(kind: str, default: float = 6.0, chest_cooldown: float = 15.0) -> float:
    if kind == "chest":
        return chest_cooldown
    spec = CATALOG.get(kind)
    return spec.cooldown if spec else default
