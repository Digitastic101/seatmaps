import streamlit as st
import json, re, itertools
from collections import defaultdict

# =========================
#  🎭 Seat Map Availability Editor
# =========================
st.set_page_config(page_title="🎭 Seat Map Availability Editor", layout="wide")
st.title("🎭 Seat Map Availability Editor")

# ---------- Utilities ----------

def norm(s: str) -> str:
    return (s or "").strip().lower()

def safe_load_json(uploaded_file):
    try:
        return json.load(uploaded_file)
    except Exception as e:
        st.error(f"Could not read JSON: {e}")
        return None

def extract_seat_list(seat_data):
    """
    Supports common structures:
    - {"seats": [...]}
    - {"data": {"seats": [...]}}
    - direct list
    """
    if seat_data is None:
        return []
    if isinstance(seat_data, list):
        return seat_data
    if isinstance(seat_data, dict):
        if "seats" in seat_data and isinstance(seat_data["seats"], list):
            return seat_data["seats"]
        if "data" in seat_data and isinstance(seat_data["data"], dict):
            if "seats" in seat_data["data"] and isinstance(seat_data["data"]["seats"], list):
                return seat_data["data"]["seats"]
    return []

def get_section_name(seat):
    # Common fields
    for k in ["section", "sectionName", "section_name", "area", "zone"]:
        if k in seat and seat[k]:
            return str(seat[k]).strip()
    # Sometimes nested
    if isinstance(seat.get("section"), dict) and seat["section"].get("name"):
        return str(seat["section"]["name"]).strip()
    return ""

def seat_label(seat):
    # Common seat label fields
    for k in ["label", "seatLabel", "seat_label", "name"]:
        if k in seat and seat[k]:
            return str(seat[k]).strip()
    # Some formats store row/number separately
    row = seat.get("row") or seat.get("Row") or ""
    num = seat.get("number") or seat.get("Number") or seat.get("seatNumber") or ""
    if row and num:
        return f"{row}{num}"
    return ""

def parse_label_to_prefix_and_num(label: str):
    """
    Turns "A12" -> ("A", 12)
          "ROW 1 - 12" already handled elsewhere, but for per-seat labels we want prefix+number.
    """
    label = (label or "").strip()
    m = re.match(r"^([A-Za-z]+)\s*0*([0-9]+)$", label.replace(" ", ""))
    if m:
        return m.group(1).upper(), int(m.group(2))
    m2 = re.match(r"^([0-9]+)$", label.replace(" ", ""))
    if m2:
        return "", int(m2.group(1))
    return None

def row_order_key(pref: str):
    # Sort row prefixes like A, B, C, AA, AB; and also allow "" first
    if pref is None:
        pref = ""
    p = pref.upper()
    if p == "":
        return (0, "")
    return (1, len(p), p)

def display_prefix(pref: str):
    pref = (pref or "").strip()
    if pref == "":
        return ""
    return f"{pref}"

def compress_ranges(nums):
    nums = sorted(set(nums))
    if not nums:
        return []
    ranges = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append((start, prev))
            start = prev = n
    ranges.append((start, prev))
    return ranges

def parse_user_ranges(text: str):
    """
    Accepts input like:
      "Stalls A1-A4, A5-A8"
      "Rausing Circle ROW 1 - 1-6"
      "A1-A10"
      "ROW 1 - 1-6"
      "1-6"
    Returns list of dicts:
      {"section": optional, "row": optional, "start": int, "end": int, "prefix": str}
    We keep it flexible and interpret later with the selected section.
    """
    text = (text or "").strip()
    if not text:
        return []

    parts = [p.strip() for p in re.split(r"[,\n]+", text) if p.strip()]
    out = []
    for p in parts:
        # Try to match "Some Section ROW X - 1-6"
        m = re.match(r"^(?:(.+?)\s+)?ROW\s*([A-Za-z0-9]+)\s*[-–]\s*([0-9]+)\s*[-–]\s*([0-9]+)$", p, re.IGNORECASE)
        if m:
            sec = (m.group(1) or "").strip()
            row = str(m.group(2)).strip()
            start = int(m.group(3))
            end = int(m.group(4))
            out.append({"section": sec, "row": row, "prefix": row, "start": start, "end": end})
            continue

        # Match "A1-A10" / "A1 - A10" / "1-6"
        m2 = re.match(r"^([A-Za-z]*)([0-9]+)\s*[-–]\s*([A-Za-z]*)([0-9]+)$", p.replace(" ", ""))
        if m2:
            pref1, s1, pref2, s2 = m2.group(1), m2.group(2), m2.group(3), m2.group(4)
            pref = (pref1 or pref2 or "").upper()
            start = int(s1)
            end = int(s2)
            out.append({"section": "", "row": pref, "prefix": pref, "start": start, "end": end})
            continue

        # Match single "A12" or "12"
        m3 = re.match(r"^([A-Za-z]*)([0-9]+)$", p.replace(" ", ""))
        if m3:
            pref = (m3.group(1) or "").upper()
            n = int(m3.group(2))
            out.append({"section": "", "row": pref, "prefix": pref, "start": n, "end": n})
            continue

        # Otherwise ignore
    return out

def section_names_from_data(seat_data):
    seats = extract_seat_list(seat_data)
    names = []
    seen = set()
    for s in seats:
        sec = get_section_name(s)
        if sec and sec.lower() not in seen:
            names.append(sec)
            seen.add(sec.lower())
    return sorted(names, key=lambda x: x.lower())

def apply_availability(seat_data, section_name, ranges, make_available: bool, price_value=None, price_only_mode=False):
    """
    Updates seat_data in-place.
    - If price_only_mode is True: do NOT change status, only change price for seats in ranges
    - Else: change status to 'AV' (available) or 'SO' (sold) for seats in ranges, optionally set price
    """
    seats = extract_seat_list(seat_data)
    sec_target = norm(section_name)

    changed = 0
    changed_price = 0

    for seat in seats:
        sec = norm(get_section_name(seat))
        if sec != sec_target:
            continue

        label = seat_label(seat)
        split = parse_label_to_prefix_and_num(label)
        if not split:
            continue

        pref, num = split
        for r in ranges:
            if norm(r.get("section","")) and norm(r.get("section","")) != sec_target:
                continue
            rp = (r.get("prefix") or "").upper()
            if rp != pref:
                continue
            if r["start"] <= num <= r["end"]:
                # matched
                if price_only_mode:
                    if price_value is not None and str(price_value).strip() != "":
                        seat["price"] = str(price_value).strip()
                        changed_price += 1
                else:
                    seat["status"] = "AV" if make_available else "SO"
                    changed += 1
                    if price_value is not None and str(price_value).strip() != "":
                        seat["price"] = str(price_value).strip()
                        changed_price += 1
                break

    return changed, changed_price

# ---------- Sidebar controls ----------
st.sidebar.header("Settings")

mode = st.sidebar.radio(
    "What do you want to do?",
    ["Set seats to Available / Sold", "Update prices only (don’t change availability)"],
    index=0
)

price_only_mode = (mode == "Update prices only (don’t change availability)")

multi_price_mode = st.sidebar.checkbox("Multiple price groups", value=False)
make_available = st.sidebar.radio("Availability action", ["Make Available", "Make Sold"], index=0)
make_available_bool = (make_available == "Make Available")

uploaded = st.file_uploader("Upload your seatmap JSON file", type=["json"])

seat_data = None
if uploaded:
    seat_data = safe_load_json(uploaded)

if seat_data:
    seats = extract_seat_list(seat_data)
    if not seats:
        st.warning("Could not find a list of seats in this JSON.")
    else:
        # ---------- Build index for copy helper ----------
        seat_index = {}  # (sec_low, pref, num) -> (seat_obj, sec_disp)
        per_section_counts = defaultdict(int)

        for seat in seats:
            sec_disp = get_section_name(seat)
            sec_low = norm(sec_disp)
            label = seat.get("label", "") or seat.get("seatLabel", "") or seat.get("name", "") or ""
            split = parse_label_to_prefix_and_num(label)
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
            if (seat.get("status","") or "").lower() == "av":
                available_count += 1
                row_map[(sec_disp, pref)].append(num)

        out_lines = []
        for (sec_disp, pref), nums in sorted(
            row_map.items(), key=lambda x: (x[0][0].lower(), row_order_key(x[0][1]))
        ):
            for s, e in compress_ranges(nums):
                disp_pref = display_prefix(pref)
                out_lines.append(f"{sec_disp} {disp_pref}{s}" if s == e else f"{sec_disp} {disp_pref}{s}-{e}")

        st.markdown("### 🪑 Copy-Paste Friendly Available Seat Ranges")
        if out_lines:
            st.text_area("📋 Paste this into 'Seat ranges' inputs below:", value=", ".join(out_lines), height=200)
            st.info(f"ℹ️ Total currently available seats in the list: **{available_count}**")
        else:
            st.info("No available seats found.")

        # Optional: split the copy/paste helper by PRICE (for AV seats)
        split_copy_by_price = st.checkbox("💷 Split the copy/paste list by price (AV seats)", value=True)

        if split_copy_by_price:
            # Build: (sec_disp, seat_price, pref) -> [seat_nums...]
            tier_row_map = defaultdict(list)
            tier_counts = defaultdict(int)

            for (sec_low, pref, num), (seat, sec_disp) in seat_index.items():
                if (seat.get("status", "") or "").lower() != "av":
                    continue
                seat_price = str(seat.get("price", "")).strip() or "∅"
                tier_row_map[(sec_disp, seat_price, pref)].append(num)
                tier_counts[(sec_disp, seat_price)] += 1

            if tier_row_map:
                st.markdown("### 💷 Copy-Paste Friendly Available Seat Ranges (split by price)")

                tier_lines = defaultdict(list)  # (sec_disp, price) -> [formatted range strings]

                for (sec_disp, price, pref), nums in sorted(
                    tier_row_map.items(),
                    key=lambda x: (x[0][0].lower(), str(x[0][1]), row_order_key(x[0][2]))
                ):
                    for s, e in compress_ranges(nums):
                        disp_pref = display_prefix(pref)
                        tier_lines[(sec_disp, price)].append(
                            f"{sec_disp} {disp_pref}{s}" if s == e else f"{sec_disp} {disp_pref}{s}-{e}"
                        )

                # Render one copy box per tier (section + price)
                for (sec_disp, price), lines_ in sorted(
                    tier_lines.items(),
                    key=lambda x: (x[0][0].lower(), str(x[0][1]))
                ):
                    count = tier_counts[(sec_disp, price)]
                    title = f"{sec_disp} — £{price}" if price != "∅" else f"{sec_disp} — (no price)"
                    with st.expander(f"{title} ({count} AV seats)", expanded=False):
                        safe_key = re.sub(r"[^a-zA-Z0-9]+", "_", f"{sec_disp}_{price}")[:80]
                        st.text_area(
                            "Copy/paste:",
                            value=", ".join(lines_),
                            height=160,
                            key=f"copy_tier_{safe_key}"
                        )
            else:
                st.info("No AV seats found to split by price.")

        # ---------- Price inputs ----------
        section_names = section_names_from_data(seat_data)

        if multi_price_mode:
            # NEW: dynamic number of price groups
            group_count = st.number_input("How many price groups?", min_value=2, max_value=50, value=4, step=1)
            groups = []
            for i in range(int(group_count)):
                st.markdown(f"#### Price Group {i+1}")
                rng = st.text_area(
                    f"Seat ranges for Group {i+1}",
                    placeholder="e.g.\nStalls A1-A4, A5-A8\nRausing Circle ROW 1 - 1-6",
                    key=f"range_{i+1}",
                    height=120
                )
                prc = st.text_input(f"Price {i+1}", placeholder="e.g. 60", key=f"price_{i+1}")
                groups.append({"range": (rng or "").strip(), "price": (prc or "").strip()})

            if price_only_mode:
                st.info("Tier editing is active (price-only mode). Availability will not change.")

        else:
            seat_range_input = st.text_area(
                "Enter seat ranges",
                placeholder="e.g.\nRausing Circle ROW 1 - 1-6\nStalls A1-A5",
                height=120
            )
            if price_only_mode:
                price_input = None
                st.info("Tier editing is active (price-only mode). Availability will not change.")
            else:
                price_input = st.text_input("Optional: set price for these seats", placeholder="e.g. 60")

        section_choice = st.selectbox("Select section to edit", options=section_names)

        # ---------- Apply changes ----------
        if st.button("Apply changes"):
            if multi_price_mode:
                total_changed = 0
                total_price_changed = 0

                for g in groups:
                    rng_text = g["range"]
                    prc = g["price"]

                    parsed = parse_user_ranges(rng_text)
                    if not parsed:
                        continue

                    changed, changed_price = apply_availability(
                        seat_data=seat_data,
                        section_name=section_choice,
                        ranges=parsed,
                        make_available=make_available_bool,
                        price_value=prc,
                        price_only_mode=price_only_mode
                    )
                    total_changed += changed
                    total_price_changed += changed_price

                if price_only_mode:
                    st.success(f"Updated prices for **{total_price_changed}** seats (availability unchanged).")
                else:
                    st.success(
                        f"Updated availability for **{total_changed}** seats, and updated prices for **{total_price_changed}** seats."
                    )

            else:
                parsed = parse_user_ranges(seat_range_input)
                if not parsed:
                    st.warning("No valid seat ranges found. Check your format.")
                else:
                    changed, changed_price = apply_availability(
                        seat_data=seat_data,
                        section_name=section_choice,
                        ranges=parsed,
                        make_available=make_available_bool,
                        price_value=price_input if not price_only_mode else None,
                        price_only_mode=price_only_mode
                    )
                    if price_only_mode:
                        st.success(f"Updated prices for **{changed_price}** seats (availability unchanged).")
                    else:
                        st.success(f"Updated availability for **{changed}** seats, and updated prices for **{changed_price}** seats.")

        # ---------- Tier editor (price-only mode helper) ----------
        if price_only_mode:
            st.markdown("---")
            st.markdown("## 💷 Tier overview (Section + Price)")
            tier_map = defaultdict(list)  # (sec_disp, price) -> [seat]
            for seat in seats:
                sec = get_section_name(seat)
                price = str(seat.get("price", "")).strip() or "∅"
                tier_map[(sec, price)].append(seat)

            # Build a small table
            tier_listing = []
            tier_keys_order = []
            for key in sorted(tier_map.keys(), key=lambda x: (x[0].lower(), str(x[1]))):
                sec_disp, price = key
                count = len(tier_map[key])
                # sample seats
                sample = []
                for s in tier_map[key][:6]:
                    sample.append(seat_label(s))
                tier_listing.append({
                    "Tier": f"{sec_disp} | {price}",
                    "Seats (count)": count,
                    "Sample": ", ".join(sample) + (" …" if count > 6 else "")
                })
                tier_keys_order.append(key)

            st.dataframe(tier_listing, use_container_width=True)

            st.markdown("#### ✏️ Update each tier (leave blank to skip)")
            tier_updates = {}
            for i, key in enumerate(tier_keys_order):
                sec_disp, price = key
                caption = f"New price for **{sec_disp}** where current price = **{price if price!='∅' else '∅ (no price)'}**"
                val = st.text_input(f"→ {caption}", key=f"tier_new_{i}", placeholder="leave blank to skip")
                val = (val or "").strip()
                if val:
                    tier_updates[key] = val

            if st.button("Apply tier price updates"):
                updated_count = 0
                for (sec_disp, price), new_price in tier_updates.items():
                    for seat in tier_map[(sec_disp, price)]:
                        seat["price"] = new_price
                        updated_count += 1
                st.success(f"Updated **{updated_count}** seats across {len(tier_updates)} tiers.")

        # ---------- Download ----------
        st.markdown("---")
        st.markdown("## Download updated JSON")
        out_json = json.dumps(seat_data, indent=2)
        st.download_button(
            "Download JSON",
            data=out_json,
            file_name="seatmap_updated.json",
            mime="application/json"
        )

else:
    st.info("Upload a seatmap JSON file to begin.")
