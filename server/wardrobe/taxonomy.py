"""Shared vocabulary: categories, seasons, occasions, colours, photo kinds.

Kept small and opinionated; the vision prompt and the filters both read from here, so the words
an agent sends are the words the gallery filters on. Owners can extend occasions in Settings.
"""

from __future__ import annotations

CATEGORIES: dict[str, list[str]] = {
    "top": ["t-shirt", "shirt", "polo", "sweater", "hoodie", "sweatshirt", "tank top", "blouse", "crop top", "henley"],
    "bottom": ["jeans", "trousers", "chinos", "shorts", "joggers", "track pants", "skirt", "leggings", "cargo pants"],
    "outerwear": ["jacket", "blazer", "coat", "puffer", "windcheater", "shacket", "cardigan", "gilet", "rain jacket"],
    "ethnic": ["kurta", "pyjama", "sherwani", "nehru jacket", "saree", "lehenga", "dupatta", "dhoti", "salwar"],
    "dress": ["dress", "jumpsuit", "co-ord set", "romper"],
    "activewear": ["sports t-shirt", "sports shorts", "track jacket", "sports bra", "compression"],
    "lounge": ["pyjamas", "lounge pants", "lounge t-shirt", "robe"],
    "innerwear": ["vest", "briefs", "boxers", "bra", "thermal"],
    "footwear": ["sneakers", "running shoes", "formal shoes", "loafers", "boots", "sandals", "slides", "flip-flops",
                 "heels", "juttis", "kolhapuris"],
    "bag": ["backpack", "tote", "sling bag", "messenger", "duffel", "laptop bag", "clutch", "wallet"],
    "accessory": ["belt", "cap", "hat", "beanie", "scarf", "muffler", "sunglasses", "watch", "tie", "pocket square",
                  "socks", "gloves", "jewellery", "cufflinks", "hair accessory"],
}

SEASONS = ["summer", "monsoon", "winter", "all-season"]

OCCASIONS = ["casual", "office", "formal", "party", "wedding", "festive", "ethnic", "sport", "travel", "lounge",
             "date", "outdoor"]

PATTERNS = ["solid", "striped", "checked", "plaid", "printed", "floral", "graphic", "polka dot", "camo",
            "colour-block", "embroidered", "textured", "denim wash", "logo"]

MATERIALS = ["cotton", "linen", "denim", "wool", "silk", "polyester", "nylon", "leather", "suede", "fleece",
             "knit", "corduroy", "viscose", "khadi", "chiffon", "velvet", "canvas", "rubber", "synthetic", "blend"]

FITS = ["slim", "regular", "relaxed", "oversized", "tailored", "skinny", "straight", "wide"]

STATUSES = ["active", "laundry", "lent", "stored", "donated", "sold", "discarded"]
INACTIVE = ("donated", "sold", "discarded")

PHOTO_KINDS = ["flat_lay", "product", "worn", "tag", "receipt", "detail", "other", "unknown"]
LINK_ROLES = ["shows", "worn", "tag", "receipt", "detail", "generated"]

# Named palette used for filters and swatches. Pixel colours are snapped to the nearest name.
PALETTE: dict[str, str] = {
    "black": "#111111",
    "charcoal": "#36393d",
    "grey": "#8a8d91",
    "white": "#f7f7f5",
    "cream": "#efe6d2",
    "beige": "#d6c3a0",
    "khaki": "#b4a27a",
    "tan": "#c08a57",
    "brown": "#6b4630",
    "olive": "#6b6b35",
    "green": "#2f8a4c",
    "mint": "#9fd8b8",
    "teal": "#1f7a7a",
    "navy": "#1d2a4d",
    "blue": "#2f5fbf",
    "light blue": "#9cc3e6",
    "purple": "#6a3d9a",
    "lavender": "#b9a6dd",
    "pink": "#e88aa8",
    "red": "#c62f2f",
    "maroon": "#6e1f2b",
    "orange": "#e77a2e",
    "mustard": "#d4a52a",
    "yellow": "#f2d23c",
    "gold": "#c9a227",
    "silver": "#c0c4c8",
}

COLOR_ALIASES = {
    "gray": "grey", "dark grey": "charcoal", "dark gray": "charcoal", "off-white": "cream", "ivory": "cream",
    "camel": "tan", "burgundy": "maroon", "wine": "maroon", "sky blue": "light blue", "baby blue": "light blue",
    "dark blue": "navy", "indigo": "navy", "royal blue": "blue", "denim": "blue", "violet": "purple",
    "lilac": "lavender", "peach": "pink", "rust": "orange", "coral": "orange", "sage": "mint", "emerald": "green",
    "forest green": "green", "army green": "olive", "sand": "beige", "taupe": "beige", "chocolate": "brown",
    "multicolor": "multicolour", "multi": "multicolour",
}

SEASON_ALIASES = {"spring": "all-season", "autumn": "all-season", "fall": "all-season", "rainy": "monsoon",
                  "all season": "all-season", "allseason": "all-season", "all": "all-season"}


def norm_color(name: str | None) -> str | None:
    if not name:
        return None
    n = name.strip().lower()
    n = COLOR_ALIASES.get(n, n)
    if n in PALETTE or n == "multicolour":
        return n
    # "navy blue", "bottle green", "dusty pink": try the longest known phrase inside the name
    words = n.replace("-", " ").split()
    for size in range(len(words), 0, -1):
        for i in range(len(words) - size + 1):
            part = " ".join(words[i:i + size])
            part = COLOR_ALIASES.get(part, part)
            if part in PALETTE:
                return part
    return None


def norm_season(name: str | None) -> str | None:
    if not name:
        return None
    n = name.strip().lower()
    n = SEASON_ALIASES.get(n, n)
    return n if n in SEASONS else None


def norm_category(cat: str | None, sub: str | None = None) -> tuple[str | None, str | None]:
    c = (cat or "").strip().lower() or None
    s = (sub or "").strip().lower() or None
    if c not in CATEGORIES and s:
        for k, subs in CATEGORIES.items():
            if s in subs:
                c = k
                break
    if c not in CATEGORIES:
        alias = {"shoes": "footwear", "shoe": "footwear", "tops": "top", "bottoms": "bottom", "jacket": "outerwear",
                 "accessories": "accessory", "bags": "bag", "sportswear": "activewear", "loungewear": "lounge",
                 "underwear": "innerwear", "traditional": "ethnic"}
        c = alias.get(c or "", c)
    return (c if c in CATEGORIES else ("accessory" if c else None)), s


def taxonomy(extra_occasions: list[str] | None = None) -> dict:
    occ = list(OCCASIONS)
    for o in extra_occasions or []:
        if o and o not in occ:
            occ.append(o)
    return {"categories": CATEGORIES, "seasons": SEASONS, "occasions": occ, "patterns": PATTERNS,
            "materials": MATERIALS, "fits": FITS, "statuses": STATUSES, "photo_kinds": PHOTO_KINDS,
            "link_roles": LINK_ROLES, "palette": PALETTE}
