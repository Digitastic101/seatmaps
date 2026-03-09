import streamlit as st
import json, re, itertools
from collections import defaultdict, Counter

st.title("🎭 Seat Map Availability Editor")

uploaded_file = st.file_uploader("Upload your seat map JSON file", type=["json"])

# ---- global UI controls ----
multi_price_mode = st.checkbox("💰 Enable multiple price groups (any number you like)")
price_only_mode = st.checkbox("💸 Only update seat prices (leave availability unchanged)")

# ───────────────── helper functions ─────────────────

BRACKET_RX = re.compile(r"(\([^)]*\))")

BLOCK_WORDS = [
    "pillar", "pillars",
    "space", "spaces",
    "blank", "blanks",
    "aisle", "aisles",
    "gap", "gaps",
    "void",
    "blocked",
    "not for sale",
    "no seat",
    "not a seat",
    "wheelchair space",
    "companion space",
]

def strip_brackets(s: str) -> str:
    return BRACKET_RX.sub("", s or "").strip()

def is_blocked_label(seat: dict) -> bool:
    """Identify seats/items that should never be on sale."""
    raw = seat.get("number", "") or ""
    label = seat.get("label", "") or ""
    notes = seat.get("notes", "") or ""
    text = strip_brackets(f"{raw} {label} {notes}".strip()).lower()

    return any(word in text for word in BLOCK_WORDS)

def compress_ranges(nums):
    nums = sorted(set(nums))
    out = []
    for _, g in itertools.groupby(enumerate(nums), lambda x: x[1] - x[0]):
        block = list(g)
        s, e = block[0][1], block[-1][1]
        out.append((s, e))
    return out

def row_order_key(pref: str):
    m = re.fullmatch(r"row(\d+)", pref)
    if m:
        return (0, -int(m.group(1)))
    return (1, pref.upper())

def display_prefix(pref: str) -> str:
    if pref.startswith("row"):
        m = re.match(r"row(\d+)$", pref)
        if m:
            return f"ROW {m.group(1)} - "
    return pref.upper()

def norm_label(s: str) -> str:
    s = strip_brackets(s or "")
    s = s.replace("–", "-").replace("—", "-")
    s = s.replace("\u00a0", " ").replace("\u202f", " ")
    s = s.lower().replace("seat", "")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"row0?(\d+)", r"row\1", s)
    return s

def split_norm_label(norm: str):
    norm = norm.replace("seat", "")
    m = re.match(r"(row\d+)-?(\d+)$", norm)
    if m:
        return m.group(1), int(m.group(2))
    m = re.match(r"([a-z][a-z\-]{0,19})(\d+)$", norm)
    if m:
        return m.group(1), int(m.group(2))
    return None

def section_names_from_data(seat_data):
    names = []
    for sec in seat_data.values():
        if isinstance(sec, dict) and sec.get("section_name") and sec.get("type", "def") != "aoi":
            names.append(re.sub(r"\s+", " ", sec["section_name"].strip()))
    return names

# Parse ranges (prices provided by fields, no inline @price)
# Returns: set[(sec_low,pref,num)]
def parse_ranges(user_text: str, section_names):
    requested = set()
    if not user_text:
        return requested

    canon_sections = {s.lower(): s for s in section_names if s}
    chunks = [c.strip() for c in re.split(r"\s*,\s*", user_text) if c.strip()]

    rx = re.compile(
        r"(?:(row)\s*(\d+)\s*(?:-|–)?\s*(\d+)\s*(?:to|–|-)\s*(\d+))"
        r"|(?:(row)\s*(\d+)\s*(?:-|–)?\s*(\d+))"
        r"|([a-z][a-z\-]{0,19})\s*(\d+)\s*(?:\s*(?:to|–|-)\s*(\d+))?",
        re.I
    )

    for chunk in chunks:
        sec_match = None
        chunk_low = chunk.lower()

        for low_name, canon in sorted(canon_sections.items(), key=lambda x: len(x[0]), reverse=True):
            if chunk_low.startswith(low_name):
                after = chunk_low[len(low_name):]
                if after == "" or (after and after[0].isspace()):
                    sec_match = (low_name, canon)
                    break

        if not sec_match:
            continue

        sec_low, sec_canon = sec_match
        rest = chunk[len(sec_canon):].strip()

        for m in rx.finditer(rest):
            if m.group(1):
                rownum = int(m.group(2))
                a = int(m.group(3))
                b = int(m.group(4))
                lo, hi = sorted((a, b))
                pref = f"row{rownum}"
                for n in range(lo, hi + 1):
                    requested.add((sec_low, pref, n))

            elif m.group(5):
                rownum = int(m.group(6))
                n = int(m.group(7))
                pref = f"row{rownum}"
                requested.add((sec_low, pref, n))

            else:
                pref = m.group(8).lower()
                a = int(m.group(9))
                b = int(m.group(10) or m.group(9))
                lo, hi = sorted((a, b))
                for n in range(lo, hi + 1):
                    requested.add((sec_low, pref, n))

    return requested

def set_row_price_to_max_only(seat_data):
    """Set row['price'] to the highest numeric seat price found in that row. Never modifies seat prices."""
    rows_updated = 0
    for sec in seat_data.values():
        if not isinstance(sec, dict) or sec.get("type") == "aoi":
            continue
        rows = sec.get("rows") or {}
        for row in rows.values():
            seats = row.get("seats") or {}
            max_price = None
            for seat in seats.values():
                s = (str(seat.get("price")) if seat.get("price") is not None else "").strip()
                if re.match(r"^\d+(?:\.\d+)?$", s):
                    p = float(s)
                    max_price = p if max_price is None else max(max_price, p)
            if max_price is not None:
                row["price"] = str(max_price)
                rows_updated += 1
    return rows_updated

# ──────────────── main UI logic ────────────────
if uploaded_file:
    try:
        seat_data = json.loads(uploaded_file.read().decode("utf-8"))
        st.success("✅ Seat map loaded successfully!")

        # Normalise section names
        for sec in seat_data.values():
            if isinstance(sec, dict) and "section_name" in sec:
                sec["section_name"] = re.sub(r"\s+", " ", sec["section_name"]).strip()

        # Build seat index: (section_low, prefix, number) -> (seat_obj, display_section)
        seat_index = {}
        per_section_counts = defaultdict(int)

        for sec in seat_data.values():
            if not isinstance(sec, dict):
                continue
            if sec.get("type", "def") == "aoi":
                continue

            sec_disp = sec.get("section_name", "Unknown Section").strip()
            sec_low = sec_disp.lower()
            rows = sec.get("rows", {}) or {}

            for row in rows.values():
                seats = row.get("seats") or {}
                for seat in seats.values():
                    # Force blocked/non-seat items to unavailable up front
                    if is_blocked_label(seat):
                        seat["status"] = "uav"

                    raw = seat.get("number", "")
                    norm = norm_label(raw)
                    split = split_norm_label(norm)
                    if not split:
                        continue

                    pref, num = split
                    key = (sec_low, pref, num)
                    seat_index[key] = (seat, sec_disp)
                    per_section_counts[sec_low] += 1

        st.caption(f"Indexed seats: {len(seat_index)} across {len(per_section_counts)} sections.")

        # Build copy/paste helper of current AV seats
        row_map = defaultdict(list)
        available_count = 0

        for (sec_low, pref, num), (seat, sec_disp) in seat_index.items():
            if (seat.get("status", "") or "").lower() == "av":
                available_count += 1
                row_map[(sec_disp, pref)].append(num)

        out_lines = []
        for (sec_disp, pref), nums in sorted(
            row_map.items(),
            key=lambda x: (x[0][0].lower(), row_order_key(x[0][1]))
        ):
            for s, e in compress_ranges(nums):
                disp_pref = display_prefix(pref)
                if s == e:
                    out_lines.append(f"{sec_disp} {disp_pref}{s}")
                else:
                    out_lines.append(f"{sec_disp} {disp_pref}{s}-{e}")

        st.markdown("### 🪑 Copy-Paste Friendly Available Seat Ranges")
        if out_lines:
            st.text_area(
                "📋 Paste this into 'Seat ranges' inputs below:",
                value=", ".join(out_lines),
                height=200
            )
            st.info(f"ℹ️ Total currently available seats in the list: **{available_count}**")
        else:
            st.info("No available seats found.")

        # ---------- Price inputs ----------
        section_names = section_names_from_data(seat_data)

        if multi_price_mode:
            group_count = st.number_input(
                "How many price groups?",
                min_value=2,
                max_value=50,
                value=4,
                step=1
            )

            groups = []
            for i in range(int(group_count)):
                st.markdown(f"#### Price Group {i+1}")
                rng = st.text_input(
                    f"Seat ranges for Group {i+1}",
                    placeholder="e.g. Stalls A1-A4, A5-A8  or  Rausing Circle ROW 1 - 1-6",
                    key=f"range_{i+1}"
                )
                prc = st.text_input(
                    f"Price {i+1}",
                    placeholder="e.g. 60",
                    key=f"price_{i+1}"
                )
                groups.append({
                    "range": (rng or "").strip(),
                    "price": (prc or "").strip()
                })

            if price_only_mode:
                st.info("Tier editing is active (price-only mode). Availability will not change.")

        else:
            seat_range_input = st.text_input(
                "Enter seat ranges",
                placeholder="Rausing Circle ROW 1 - 1-6, Stalls A1-A5"
            )

            if price_only_mode:
                price_input = None
                st.info("Tier editing is active (price-only mode). Availability will not change.")
            else:
                price_input = st.text_input("Enter new price", placeholder="e.g. 65")

        # ----- Tier Detection UI -----
        tier_new_values = {}
        tier_listing = []
        tier_keys_order = []

        if price_only_mode:
            tiers = defaultdict(list)  # (sec_disp, price) -> [ (sec_disp, pref, num, seat) ]

            for (sec_low, pref, num), (seat, sec_disp) in seat_index.items():
                if (seat.get("status", "") or "").lower() != "av":
                    continue
                seat_price = str(seat.get("price", "")).strip() or "∅"
                key = (sec_disp, seat_price)
                tiers[key].append((sec_disp, pref, num, seat))

            st.markdown("### 🧮 Price tiers (AV seats, grouped by section)")
            if not tiers:
                st.info("No AV tiers found.")
            else:
                for i, (key, seats) in enumerate(
                    sorted(tiers.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1]))
                ):
                    sec_disp, price = key
                    tier_label = f"{sec_disp} — £{price}" if price != "∅" else f"{sec_disp} — (no price)"
                    count = len(seats)

                    sample_locs = []
                    for (sdisp, pref, num, _seat) in seats[:6]:
                        pp = "ROW " + pref[3:] if pref.startswith("row") else pref.upper()
                        sample_locs.append(f"{sdisp} {pp}-{num}")

                    tier_listing.append({
                        "Tier": tier_label,
                        "Seats (count)": count,
                        "Sample": ", ".join(sample_locs) + (" …" if count > 6 else "")
                    })
                    tier_keys_order.append(key)

                st.dataframe(tier_listing, use_container_width=True)
                st.markdown("#### ✏️ Update each tier (leave blank to skip)")

                for i, key in enumerate(tier_keys_order):
                    sec_disp, price = key
                    caption = (
                        f"New price for **{sec_disp}** where current price = "
                        f"**{price if price != '∅' else '∅ (no price)'}**"
                    )
                    val = st.text_input(
                        f"→ {caption}",
                        key=f"tier_new_{i}",
                        placeholder="leave blank to skip"
                    )
                    val = (val or "").strip()
                    if val:
                        if not re.match(r"^\d+(?:\.\d+)?$", val):
                            st.warning(
                                f"'{val}' doesn’t look like a number, this tier will be skipped unless corrected."
                            )
                        else:
                            tier_new_values[key] = val

        # ----- Parse input ranges -----
        requested_single = set()
        parsed_groups = []

        if multi_price_mode:
            for g in groups:
                seats = parse_ranges(g["range"], section_names) if g["range"] else set()
                parsed_groups.append({"seats": seats, "price": g["price"]})

            all_keys = [k for g in parsed_groups for k in g["seats"]]
            dup_counts = Counter(all_keys)
            overlaps = {k for k, c in dup_counts.items() if c > 1}
            total_targets = sum(len(g["seats"]) for g in parsed_groups)

            st.markdown("### 🔎 Parsed Seat Targets (Preview)")
            st.write(
                f"Groups: **{len(parsed_groups)}** | "
                f"Total seats targeted (with duplicates): **{total_targets}** | "
                f"Overlapping seats: **{len(overlaps)}**"
            )

            if overlaps:
                sec_title = {s.lower(): s for s in section_names}

                def pretty(k):
                    sec_low, pref, n = k
                    sec_disp = sec_title.get(sec_low, "?")
                    pp = "ROW " + pref[3:] if pref.startswith("row") else pref.upper()
                    return f"{sec_disp} {pp}-{n}"

                sample = ", ".join(pretty(k) for k in sorted(list(overlaps))[:12])
                st.warning(
                    f"⚠️ Overlaps detected. Earlier groups take precedence. "
                    f"Sample: {sample}{' …' if len(overlaps) > 12 else ''}"
                )
        else:
            if "seat_range_input" in locals() and seat_range_input:
                requested_single = parse_ranges(seat_range_input, section_names)
                st.markdown("### 🔎 Parsed Seat Targets (Preview)")
                st.write(f"Targets parsed: **{len(requested_single)}** seats")

        # ----- Apply updates -----
        if st.button("▶️ Go"):
            matched = []
            updated_seats = []
            missing = []

            # 1) Apply tier price edits first
            if price_only_mode and tier_new_values:
                changed = 0
                for (sec_low, pref, num), (seat, sec_disp) in seat_index.items():
                    if (seat.get("status", "") or "").lower() != "av":
                        continue
                    cur_price = str(seat.get("price", "")).strip() or "∅"
                    new_p = tier_new_values.get((sec_disp, cur_price))
                    if new_p:
                        seat["price"] = str(new_p)
                        changed += 1

                if changed:
                    st.success(f"💸 Updated {changed} AV seats via tier edits.")

            # 2) Multiple price groups mode
            if multi_price_mode:
                assignment = {}  # seat_key -> (group_index, price_str)

                for idx, g in enumerate(parsed_groups):
                    price = (g["price"] or "").strip()
                    for key in g["seats"]:
                        if key not in seat_index:
                            missing.append(key)
                            continue
                        if key in assignment:
                            continue
                        assignment[key] = (idx, price)

                # Availability changes
                if not price_only_mode:
                    for key, (idx, _price) in assignment.items():
                        seat, sec_disp = seat_index[key]

                        if is_blocked_label(seat):
                            seat["status"] = "uav"
                            continue

                        if (seat.get("status", "") or "").lower() != "av":
                            seat["status"] = "av"
                            updated_seats.append({
                                "Section": sec_disp,
                                "Seat": seat.get("number", ""),
                                "Status": "av",
                                "Price": seat.get("price", "")
                            })

                        matched.append(f"{sec_disp} {seat.get('number', '').strip()}")

                # Apply prices
                for key, (idx, price) in assignment.items():
                    if price:
                        seat, _ = seat_index[key]
                        seat["price"] = str(price)

                # Auto set all non-target seats to UAV
                if not price_only_mode:
                    targeted = set(assignment.keys())
                    turned_off = 0

                    for key, (seat, _) in seat_index.items():
                        if key not in targeted:
                            if (seat.get("status", "") or "").lower() != "uav":
                                seat["status"] = "uav"
                                turned_off += 1

                    if turned_off:
                        st.info(f"🔕 Set {turned_off} non-targeted seats to UAV.")

            # 3) Single range + price mode
            else:
                if not price_only_mode and requested_single:
                    for key in requested_single:
                        if key in seat_index:
                            seat, sec_disp = seat_index[key]

                            if is_blocked_label(seat):
                                seat["status"] = "uav"
                                continue

                            if (seat.get("status", "") or "").lower() != "av":
                                seat["status"] = "av"
                                updated_seats.append({
                                    "Section": sec_disp,
                                    "Seat": seat.get("number", ""),
                                    "Status": "av",
                                    "Price": seat.get("price", "")
                                })

                            matched.append(f"{sec_disp} {seat.get('number', '').strip()}")
                        else:
                            missing.append(key)

                if not price_only_mode and "price_input" in locals() and price_input:
                    for key in requested_single:
                        if key in seat_index:
                            seat, _ = seat_index[key]
                            seat["price"] = str(price_input)

                if not price_only_mode:
                    targeted = requested_single
                    turned_off = 0

                    for key, (seat, _) in seat_index.items():
                        if key not in targeted:
                            if (seat.get("status", "") or "").lower() != "uav":
                                seat["status"] = "uav"
                                turned_off += 1

                    if turned_off:
                        st.info(f"🔕 Set {turned_off} non-targeted seats to UAV.")

            # Final enforcement for blocked labels
            blocked_kept_uav = 0
            for key, (seat, _) in seat_index.items():
                if is_blocked_label(seat) and (seat.get("status", "").lower() != "uav"):
                    seat["status"] = "uav"
                    blocked_kept_uav += 1

            if blocked_kept_uav:
                st.info(
                    f"🚫 Kept {blocked_kept_uav} blocked items "
                    f"(pillar, space, aisle, etc.) as UAV."
                )

            # Post-op messaging
            if not price_only_mode:
                if matched:
                    st.markdown("### ✅ Availability Updated")
                    st.write(", ".join(sorted(matched)))

                if missing:
                    sec_title = {s.lower(): s for s in section_names}
                    pretty = [
                        f"{sec_title.get(sec, '?')} "
                        f"{(pref.upper() if not pref.startswith('row') else 'ROW ' + pref[3:])}-{n}"
                        for (sec, pref, n) in sorted(set(missing))
                    ]
                    st.warning("⚠️ Seats not found: " + ", ".join(pretty))

            if updated_seats:
                st.markdown("### 🎟️ Updated Seats")
                st.dataframe(updated_seats, use_container_width=True)

            # Row price = max seat price in row
            rows_updated = set_row_price_to_max_only(seat_data)
            if rows_updated:
                st.info(f"📏 Row prices set to the highest seat price in {rows_updated} rows.")

            # Visibility check for seats below row price
            mismatches = []
            for sec in seat_data.values():
                if not isinstance(sec, dict) or sec.get("type") == "aoi":
                    continue

                rows = sec.get("rows") or {}
                for row_name, row in rows.items():
                    row_price_s = (str(row.get("price")) if row.get("price") is not None else "").strip()
                    row_price = float(row_price_s) if re.match(r"^\d+(?:\.\d+)?$", row_price_s) else None
                    if row_price is None:
                        continue

                    seats = row.get("seats") or {}
                    for seat in seats.values():
                        seat_num = seat.get("number", "")
                        seat_price_s = (str(seat.get("price")) if seat.get("price") is not None else "").strip()
                        if re.match(r"^\d+(?:\.\d+)?$", seat_price_s):
                            seat_price = float(seat_price_s)
                            if seat_price < row_price:
                                mismatches.append({
                                    "Section": sec.get("section_name", ""),
                                    "Row": row_name,
                                    "Seat": seat_num,
                                    "Row Price": row_price_s,
                                    "Seat Price": seat_price_s
                                })

            if mismatches:
                st.markdown("### 🔎 Seats priced below their row (expected, just for visibility)")
                st.dataframe(mismatches[:300], use_container_width=True)

            # Sample summary
            st.markdown("### 📊 Seat Price Summary (sample)")
            sample = []
            for i, ((sec_low, pref, num), (seat, sec_disp)) in enumerate(sorted(seat_index.items())[:300]):
                sample.append({
                    "Section": sec_disp,
                    "Seat": seat.get("number", ""),
                    "Price": seat.get("price", "")
                })
            st.dataframe(sample, use_container_width=True)

            st.download_button(
                "Download Updated JSON",
                json.dumps(seat_data, indent=2),
                file_name="updated_seatmap.json",
                mime="application/json"
            )

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
