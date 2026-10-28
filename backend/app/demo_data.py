"""Seeded demo festival: fictional acts, hand-written taste profiles, and
deliberately seeded schedule clashes. Used when QLOO_API_KEY is missing so the
app stays fully demonstrable offline. Demo data is clearly labelled as such.
"""

# Template for a fresh user-built festival: same grid as the demo, no acts.
# User acts come from live Qloo search; entity ids are real Qloo entity ids.
FESTIVAL_TEMPLATE = {
    "name": "My Festival",
    "mode": "live",
    "note": "User-built lineup — artists are added via live Qloo search.",
    "stages": [
        {"id": "main", "name": "Main Stage"},
        {"id": "second", "name": "Second Stage"},
        {"id": "third", "name": "Third Stage"},
    ],
    "slots": [
        {"id": "t1", "label": "17:00", "start": "17:00", "end": "18:00"},
        {"id": "t2", "label": "18:00", "start": "18:00", "end": "19:00"},
        {"id": "t3", "label": "19:00", "start": "19:00", "end": "20:00"},
        {"id": "t4", "label": "20:00", "start": "20:00", "end": "21:00"},
        {"id": "t5", "label": "21:00", "start": "21:00", "end": "22:00"},
        {"id": "t6", "label": "22:00", "start": "22:00", "end": "23:00"},
    ],
    "acts": [],
}

DEMO_FESTIVAL = {
    "name": "Qloo Fest 2026",
    "mode": "demo",
    "note": "Seeded demo dataset — fictional artists, no live Qloo data.",
    "stages": [
        {"id": "main", "name": "Main Stage"},
        {"id": "pulse", "name": "Pulse Stage"},
        {"id": "grove", "name": "Grove Stage"},
        {"id": "oasis", "name": "Oasis Stage"},
    ],
    "slots": [
        {"id": "t1", "label": "17:00", "start": "17:00", "end": "18:00"},
        {"id": "t2", "label": "18:00", "start": "18:00", "end": "19:00"},
        {"id": "t3", "label": "19:00", "start": "19:00", "end": "20:00"},
        {"id": "t4", "label": "20:00", "start": "20:00", "end": "21:00"},
        {"id": "t5", "label": "21:00", "start": "21:00", "end": "22:00"},
        {"id": "t6", "label": "22:00", "start": "22:00", "end": "23:00"},
    ],
    "acts": [
        # --- Electronic pair clash @ t3 (Pulse vs Grove) ---
        {"id": "a1", "name": "Neon Cascade", "entity_id": "demo:neon-cascade",
         "stage_id": "pulse", "slot_id": "t3", "duration_min": 60, "fixed": False},
        {"id": "a2", "name": "Pulse Machine", "entity_id": "demo:pulse-machine",
         "stage_id": "grove", "slot_id": "t3", "duration_min": 60, "fixed": False},
        # --- Indie rock pair clash @ t4 (Main vs Oasis) ---
        {"id": "a3", "name": "The Wild Violets", "entity_id": "demo:wild-violets",
         "stage_id": "main", "slot_id": "t4", "duration_min": 60, "fixed": False},
        {"id": "a4", "name": "Static Bloom", "entity_id": "demo:static-bloom",
         "stage_id": "oasis", "slot_id": "t4", "duration_min": 60, "fixed": False},
        # --- Hip-hop pair clash @ t5 (Grove vs Oasis) ---
        {"id": "a5", "name": "Grit & Groove", "entity_id": "demo:grit-and-groove",
         "stage_id": "grove", "slot_id": "t5", "duration_min": 60, "fixed": False},
        {"id": "a6", "name": "Verse City", "entity_id": "demo:verse-city",
         "stage_id": "oasis", "slot_id": "t5", "duration_min": 60, "fixed": False},
        # --- Folk pair clash @ t1 (Grove vs Oasis) ---
        {"id": "a7", "name": "Willow & Pine", "entity_id": "demo:willow-and-pine",
         "stage_id": "oasis", "slot_id": "t1", "duration_min": 60, "fixed": False},
        {"id": "a8", "name": "The Harvest Choir", "entity_id": "demo:harvest-choir",
         "stage_id": "grove", "slot_id": "t1", "duration_min": 60, "fixed": False},
        # --- Classical pair clash @ t2 (Main vs Grove) ---
        {"id": "a9", "name": "Ensemble Aurum", "entity_id": "demo:ensemble-aurum",
         "stage_id": "main", "slot_id": "t2", "duration_min": 60, "fixed": False},
        {"id": "a10", "name": "The Chamber Collective", "entity_id": "demo:chamber-collective",
         "stage_id": "grove", "slot_id": "t2", "duration_min": 60, "fixed": False},
        # --- FIXED pop headliners clash @ t6 — locked, cannot be fixed ---
        {"id": "a11", "name": "Aurora Lane", "entity_id": "demo:aurora-lane",
         "stage_id": "main", "slot_id": "t6", "duration_min": 60, "fixed": True},
        {"id": "a12", "name": "Skyline", "entity_id": "demo:skyline",
         "stage_id": "pulse", "slot_id": "t6", "duration_min": 60, "fixed": True},
        # --- Fillers ---
        {"id": "a13", "name": "Iron Howl", "entity_id": "demo:iron-howl",
         "stage_id": "main", "slot_id": "t1", "duration_min": 60, "fixed": False},
        {"id": "a14", "name": "Blue Note Society", "entity_id": "demo:blue-note-society",
         "stage_id": "pulse", "slot_id": "t2", "duration_min": 60, "fixed": False},
        {"id": "a15", "name": "Island Roots", "entity_id": "demo:island-roots",
         "stage_id": "oasis", "slot_id": "t2", "duration_min": 60, "fixed": False},
        {"id": "a16", "name": "Velvet Soul", "entity_id": "demo:velvet-soul",
         "stage_id": "main", "slot_id": "t3", "duration_min": 60, "fixed": False},
        {"id": "a17", "name": "Ritmo Solar", "entity_id": "demo:ritmo-solar",
         "stage_id": "main", "slot_id": "t5", "duration_min": 60, "fixed": False},
        {"id": "a18", "name": "Desert Winds", "entity_id": "demo:desert-winds",
         "stage_id": "pulse", "slot_id": "t1", "duration_min": 60, "fixed": False},
        {"id": "a19", "name": "Star Chasers", "entity_id": "demo:star-chasers",
         "stage_id": "pulse", "slot_id": "t4", "duration_min": 60, "fixed": False,
         "allowed_stages": ["main", "pulse"]},
        # --- Missing-profile act: excluded from similarity, shown honestly ---
        {"id": "a20", "name": "Enigma Collective", "entity_id": "demo:enigma-collective",
         "stage_id": "pulse", "slot_id": "t5", "duration_min": 60, "fixed": False},
    ],
}

# Hand-written demo taste profiles. Tag ids follow Qloo's observed patterns.
DEMO_PROFILES = {
    "demo:neon-cascade": {
        "entity_id": "demo:neon-cascade", "name": "Neon Cascade", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:electronic", "urn:tag:genre:music:house", "urn:tag:genre:music:dance"],
        "audience_tags": ["urn:tag:audience:qloo:energetic", "urn:tag:audience:qloo:party"],
        "style_tags": ["urn:tag:style:qloo:upbeat", "urn:tag:style:qloo:vibrant"],
        "music_tags": ["urn:tag:music:qloo:driving", "urn:tag:music:qloo:synthetic"],
    },
    "demo:pulse-machine": {
        "entity_id": "demo:pulse-machine", "name": "Pulse Machine", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:electronic", "urn:tag:genre:music:techno", "urn:tag:genre:music:dance"],
        "audience_tags": ["urn:tag:audience:qloo:energetic"],
        "style_tags": ["urn:tag:style:qloo:intense", "urn:tag:style:qloo:vibrant"],
        "music_tags": ["urn:tag:music:qloo:driving", "urn:tag:music:qloo:hypnotic"],
    },
    "demo:wild-violets": {
        "entity_id": "demo:wild-violets", "name": "The Wild Violets", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:indie_rock", "urn:tag:genre:music:alternative_rock", "urn:tag:genre:music:rock"],
        "audience_tags": ["urn:tag:audience:qloo:devoted", "urn:tag:audience:qloo:nostalgic"],
        "style_tags": ["urn:tag:style:qloo:melancholic", "urn:tag:style:qloo:raw"],
        "music_tags": ["urn:tag:music:qloo:guitar_driven"],
    },
    "demo:static-bloom": {
        "entity_id": "demo:static-bloom", "name": "Static Bloom", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:alternative_rock", "urn:tag:genre:music:rock", "urn:tag:genre:music:shoegaze"],
        "audience_tags": ["urn:tag:audience:qloo:devoted", "urn:tag:audience:qloo:intellectual"],
        "style_tags": ["urn:tag:style:qloo:atmospheric", "urn:tag:style:qloo:melancholic"],
        "music_tags": ["urn:tag:music:qloo:guitar_driven", "urn:tag:music:qloo:ethereal"],
    },
    "demo:grit-and-groove": {
        "entity_id": "demo:grit-and-groove", "name": "Grit & Groove", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:hip_hop", "urn:tag:genre:music:rap", "urn:tag:genre:music:trap"],
        "audience_tags": ["urn:tag:audience:qloo:streetwise", "urn:tag:audience:qloo:energetic"],
        "style_tags": ["urn:tag:style:qloo:gritty", "urn:tag:style:qloo:confident"],
        "music_tags": ["urn:tag:music:qloo:beat_driven"],
    },
    "demo:verse-city": {
        "entity_id": "demo:verse-city", "name": "Verse City", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:rap", "urn:tag:genre:music:hip_hop", "urn:tag:genre:music:rnb"],
        "audience_tags": ["urn:tag:audience:qloo:streetwise", "urn:tag:audience:qloo:dedicated"],
        "style_tags": ["urn:tag:style:qloo:smooth", "urn:tag:style:qloo:confident"],
        "music_tags": ["urn:tag:music:qloo:beat_driven", "urn:tag:music:qloo:lyrical"],
    },
    "demo:willow-and-pine": {
        "entity_id": "demo:willow-and-pine", "name": "Willow & Pine", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:folk", "urn:tag:genre:music:americana", "urn:tag:genre:music:acoustic"],
        "audience_tags": ["urn:tag:audience:qloo:nostalgic", "urn:tag:audience:qloo:laid_back"],
        "style_tags": ["urn:tag:style:qloo:warm", "urn:tag:style:qloo:organic"],
        "music_tags": ["urn:tag:music:qloo:acoustic"],
    },
    "demo:harvest-choir": {
        "entity_id": "demo:harvest-choir", "name": "The Harvest Choir", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:folk", "urn:tag:genre:music:country", "urn:tag:genre:music:acoustic"],
        "audience_tags": ["urn:tag:audience:qloo:nostalgic", "urn:tag:audience:qloo:spiritual"],
        "style_tags": ["urn:tag:style:qloo:warm", "urn:tag:style:qloo:organic"],
        "music_tags": ["urn:tag:music:qloo:acoustic", "urn:tag:music:qloo:vocal"],
    },
    "demo:ensemble-aurum": {
        "entity_id": "demo:ensemble-aurum", "name": "Ensemble Aurum", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:classical", "urn:tag:genre:music:romantic"],
        "audience_tags": ["urn:tag:audience:qloo:cultivated", "urn:tag:audience:qloo:intellectual"],
        "style_tags": ["urn:tag:style:qloo:refined", "urn:tag:style:qloo:emotive"],
        "music_tags": ["urn:tag:music:qloo:orchestral"],
    },
    "demo:chamber-collective": {
        "entity_id": "demo:chamber-collective", "name": "The Chamber Collective", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:classical", "urn:tag:genre:music:chamber_music"],
        "audience_tags": ["urn:tag:audience:qloo:cultivated", "urn:tag:audience:qloo:intellectual"],
        "style_tags": ["urn:tag:style:qloo:refined", "urn:tag:style:qloo:intimate"],
        "music_tags": ["urn:tag:music:qloo:orchestral", "urn:tag:music:qloo:delicate"],
    },
    "demo:aurora-lane": {
        "entity_id": "demo:aurora-lane", "name": "Aurora Lane", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:pop", "urn:tag:genre:music:dance_pop", "urn:tag:genre:music:electronic"],
        "audience_tags": ["urn:tag:audience:qloo:mainstream", "urn:tag:audience:qloo:devoted"],
        "style_tags": ["urn:tag:style:qloo:upbeat", "urn:tag:style:qloo:polished"],
        "music_tags": ["urn:tag:music:qloo:anthemic"],
    },
    "demo:skyline": {
        "entity_id": "demo:skyline", "name": "Skyline", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:pop", "urn:tag:genre:music:synthpop", "urn:tag:genre:music:electronic"],
        "audience_tags": ["urn:tag:audience:qloo:mainstream", "urn:tag:audience:qloo:young"],
        "style_tags": ["urn:tag:style:qloo:upbeat", "urn:tag:style:qloo:polished"],
        "music_tags": ["urn:tag:music:qloo:anthemic", "urn:tag:music:qloo:synthetic"],
    },
    "demo:iron-howl": {
        "entity_id": "demo:iron-howl", "name": "Iron Howl", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:metal", "urn:tag:genre:music:heavy_metal", "urn:tag:genre:music:hard_rock"],
        "audience_tags": ["urn:tag:audience:qloo:intense", "urn:tag:audience:qloo:devoted"],
        "style_tags": ["urn:tag:style:qloo:aggressive", "urn:tag:style:qloo:powerful"],
        "music_tags": ["urn:tag:music:qloo:heavy"],
    },
    "demo:blue-note-society": {
        "entity_id": "demo:blue-note-society", "name": "Blue Note Society", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:jazz", "urn:tag:genre:music:bebop"],
        "audience_tags": ["urn:tag:audience:qloo:cultivated", "urn:tag:audience:qloo:intellectual"],
        "style_tags": ["urn:tag:style:qloo:sophisticated", "urn:tag:style:qloo:improvisational"],
        "music_tags": ["urn:tag:music:qloo:instrumental"],
    },
    "demo:island-roots": {
        "entity_id": "demo:island-roots", "name": "Island Roots", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:reggae", "urn:tag:genre:music:dub"],
        "audience_tags": ["urn:tag:audience:qloo:laid_back", "urn:tag:audience:qloo:spiritual"],
        "style_tags": ["urn:tag:style:qloo:sunny", "urn:tag:style:qloo:organic"],
        "music_tags": ["urn:tag:music:qloo:groovy"],
    },
    "demo:velvet-soul": {
        "entity_id": "demo:velvet-soul", "name": "Velvet Soul", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:soul", "urn:tag:genre:music:rnb", "urn:tag:genre:music:funk"],
        "audience_tags": ["urn:tag:audience:qloo:nostalgic", "urn:tag:audience:qloo:romantic"],
        "style_tags": ["urn:tag:style:qloo:smooth", "urn:tag:style:qloo:warm"],
        "music_tags": ["urn:tag:music:qloo:vocal", "urn:tag:music:qloo:groovy"],
    },
    "demo:ritmo-solar": {
        "entity_id": "demo:ritmo-solar", "name": "Ritmo Solar", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:latin", "urn:tag:genre:music:salsa", "urn:tag:genre:music:cumbia"],
        "audience_tags": ["urn:tag:audience:qloo:energetic", "urn:tag:audience:qloo:family"],
        "style_tags": ["urn:tag:style:qloo:festive", "urn:tag:style:qloo:vibrant"],
        "music_tags": ["urn:tag:music:qloo:danceable"],
    },
    "demo:desert-winds": {
        "entity_id": "demo:desert-winds", "name": "Desert Winds", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:world", "urn:tag:genre:music:ambient", "urn:tag:genre:music:new_age"],
        "audience_tags": ["urn:tag:audience:qloo:cultivated", "urn:tag:audience:qloo:spiritual"],
        "style_tags": ["urn:tag:style:qloo:atmospheric", "urn:tag:style:qloo:meditative"],
        "music_tags": ["urn:tag:music:qloo:ethereal"],
    },
    "demo:star-chasers": {
        "entity_id": "demo:star-chasers", "name": "Star Chasers", "source": "demo",
        "genre_tags": ["urn:tag:genre:music:k_pop", "urn:tag:genre:music:pop", "urn:tag:genre:music:electronic"],
        "audience_tags": ["urn:tag:audience:qloo:young", "urn:tag:audience:qloo:devoted"],
        "style_tags": ["urn:tag:style:qloo:polished", "urn:tag:style:qloo:vibrant"],
        "music_tags": ["urn:tag:music:qloo:danceable"],
    },
    "demo:enigma-collective": {
        "entity_id": "demo:enigma-collective", "name": "Enigma Collective", "source": "demo",
        "missing": True,
        "note": "Missing taste profile — no usable tags. Excluded from similarity scores.",
        "genre_tags": [], "audience_tags": [], "style_tags": [], "music_tags": [],
    },
}
