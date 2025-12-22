import streamlit as st
import json, re
from collections import defaultdict

# =========================
#  🎭 Seat Map Availability Editor
# =========================
st.set_page_config(page_title="🎭 Seat Map Availability Editor", layout="wide")
st.title("🎭 Seat Map Availability Editor")

# ---------- JSON helpers for YOUR file shape ----------

def safe_load_json(uploaded_file):
    try:
        return json.load(uploaded_file)
    except Exception as e:
        st.error(f"Could not read JSON: {e}")
        return None

def iter_seats_with_section(seat_data):
    """
    Your JSON looks like:
    top-level dict -> element dicts
      element["section_name"]
      element["rows"] -> row dicts
        row["seats"] -> seat dicts
          seat["number"] like "ROW 3 - 88"
          seat["status"], seat["price"]
    Yields (seat_obj_dict, section_name)
    """
    if not isinstance(seat_data, dict):
        return

    for _element_id, element in seat_data.items():
        if not isinstance(element, dict):
            continue

        section = element.get("section_name") or element.get("sectionName") or element.get("section") or ""
        rows = element.get("rows")
        if not isinstance(rows, dict):
            continue

        for _row_id, row in rows.items():
            if not isinstance(row, dict):
                continue
            seats = row.get("seats")
            if not isinstance(seats, dict):
                continue

            for _seat_id, seat in seats.items():
                if isinstance(seat, dict):
                    yield seat, str(section).strip()

def section_names_from_data(seat_data):
    names = set()
    for _seat, section in iter_seats_with_section(seat_data):
        if section:
            names.add(section)
    return sorted(names, key=lambda x: x.lower())

# ---------- Seat parsing + range logic ----------

def norm(s: str) -> str:
    return (s or "").strip().lower()

def parse_seat_number_field(number_field: str):
    """
    seat["number"] in your JSON often looks like:
      "ROW 3 - 88"
      "ROW 12 - 101"
    Returns (row_label, seat_num_int) like ("ROW 3", 88)
    """
    s = (number_field or "").strip()
    m = re.match(r"^(ROW\s*\d+)\s*-\s*(\d+)$", s, re.IGNORECASE)
    if not m:
        return None
    row = m.group(1).upper().replace("  ", " ").strip()
    num = int(m.group(2))
    return row, num

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

def row_order_key(row_label: str):
    s = (row_label or "").upper()
    m = re.match(r"^ROW\s*(\d+)$", s)
    if m:
        return (0, int(m.group(1)))
    return (1, s)

def parse_user_ranges(text: str):
    """
    Accepts lines like:
      ROW 3 - 88-95
      ROW 12 - 101
    Also accepts commas/newlines.
    Returns list of dicts: {"row": "ROW 3", "start": 88, "end": 95}
    """
    text = (text or "").strip()
    if not text:
        return []

    parts = [p.strip() for p in re.split(r"[,\n]+", text) if p.strip()]
    out = []

    for p in parts:
        # ROW X - A-B
        m = re.match(r"^(ROW\s*\d+)\s*-\s*(\d+)\s*-\s*(\d+)$", p, re.IGNORECASE)
        if m:
            row = m.group(1).upper().replace("  ", " ").strip()
            start = int(m.group(2))
            end = int(m.group(3))
            out.append({"row": row, "start": min(start, end), "end": max(start, end)})
            continue

        # ROW X - N
        m2 = re.match(r"^(ROW\s*\d+)\s*-\s*(\d+)$", p, re.IGNORECASE)
        if m2:
            row = m2.group(1).upper().replace("  ", " ").strip()
            n = int(m2.group(2))
            out.append({"row": row, "start": n, "end": n})
            continue

    return out

def apply_changes(seat_data, section_name, ranges, make_available: bool, price_value=None, price_only_mode=False):
    """
    Updates seats in-place within your JSON structure.
    """
    changed_status = 0
    changed_price = 0

    sec_target = norm(section_name)

    for seat, sec in iter_seats_with_section(seat_data):
        if norm(sec) != sec_target:
            continue

        parsed = parse_seat_number_field(seat.get("number", ""))
        if not parsed:
            continue

        row_label, seat_num = parsed

        for r in ranges:
            if r["row"] != row_label:
                continue
            if r["start"] <= seat_num <= r["end"]:
                if price_only_mode:
                    if price_value is not None and str(price_value).strip() != "":
                        seat["price"] = str(price_value).strip()
                        changed_price += 1
                else:
                    seat["status"] = "av" if make_available else "so"
                    changed_status += 1
                    if price_value is not None and str(price_value).strip() != "":
                        seat["price"] = str(price_value).strip()
                        changed_price += 1
                break

    return changed_status, changed_price

# ---------- Auto-unavailable for text seats ----------

TEXT_BLOCK_KEYWORDS = [
    "PILLAR", "PILAR", "EMPTY", "BLANK", "SPACE"
]

def is_text_placeholder_seat(seat: dict) -> bool:
    """
    Marks seats that are not real numbered seats (or explicitly say they're placeholders).
    We check a few likely fields: number, label, text, name, type.
    """
    # 1) If a seat has 'type' that hints it's text/placeholder
    t = str(seat.get("type", "") or "").strip().lower()
    if t in {"text", "label", "placeholder", "block"}:
        return True

    # 2) Look for keywords in common string fields
    candidates = []
    for k in ["number", "label", "text", "name", "seat_label", "seatLabel"]:
        v = seat.get(k)
        if isinstance(v, str) and v.strip():
            candidates.append(v.strip())

    joined = " | ".join(candidates).upper()
    if any(kw in joined for kw in TEXT_BLOCK_KEYWORDS):
        return True

    # 3) If it has a 'number' field but it does NOT match "ROW X - N",
    #    treat it as non-seat text (this catches odd blocks like "PILLAR" etc.)
    num_field = seat.get("number")
    if isinstance(num_field, str) and num_field.strip():
        if parse_seat_number_field(num_field) is None:
            # If it's not a normal seat format, assume it's a label block
            return True

    return False

def auto_make_text_unavailable(seat_data):
    """
    On load: any seat that looks like PILLAR / EMPTY / BLANK / SPACE etc becomes unavailable (status='so').
    Returns count changed.
    """
    changed = 0
    for seat, _sec in iter_seats_with_section(seat_data):
        if is_text_placeholder_seat(seat):
            # Only change if not already unavailable
            if norm(seat.get("status", "")) != "so":
                seat["status"] = "so"
                changed += 1
    return changed

# =========================
# Settings (MAIN PAGE)
# =========================

st.markdown("## Settings")

col1, col2, col3, col4 = st.columns([2.2, 1.4, 1.6, 1.8])

with col1:
    mode = st.radio(
        "What do you want to do?",
        ["Set seats to Available / Sold", "Update prices only (don’t change availability)"],
        index=0
    )

with col2:
    multi_price_mode = st.checkbox("Multiple price groups", value=False)

with col3:
    make_available = st.radio(
        "Availability action",
        ["Make Available", "Make Sold"],
        index=0
    )

with col4:
    auto_text_block = st.checkbox(
        "Auto-make PILLAR/EMPTY/BLANK/SPACE unavailable",
        value=True
    )

price_only_mode = (mode == "Update prices only (don’t change availability)")
make_available_bool = (make_available == "Make Available")

st.markdown("---")

uploaded = st.file_uploader("Upload your seatmap JSON file", type=["json"])

seat_data = None
if uploaded:
    seat_data = safe_load_json(uploaded)

if not seat_data:
    st.info("Upload a seatmap JSON file to begin.")
    st.stop()

# Auto-mark text blocks unavailable (if enabled)
if auto_text_block:
    auto_changed = auto_make_text_unavailable(seat_data)
    if auto_changed > 0:
        st.info(f"Auto-set **{auto_changed}** text/placeholder seats to unavailable (status=so).")

# Sections
sections = section_names_from_data(seat_data)
if not sections:
    st.error("I couldn’t find any sections in this JSON (no seats found under rows → seats).")
    st.stop()

section_choice = st.selectbox("Select section to edit", options=sections)

# ---------- Copy helpers (overall + by price) ----------

row_to_nums = defaultdict(list)
row_price_to_nums = defaultdict(lambda: defaultdict(list))  # price -> row -> nums
total_av = 0

for seat, sec in iter_seats_with_section(seat_data):
    if norm(sec) != norm(section_choice):
        continue
    if norm(seat.get("status", "")) != "av":
        continue

    parsed = parse_seat_number_field(seat.get("number", ""))
    if not parsed:
        continue

    row_label, seat_num = parsed
    row_to_nums[row_label].append(seat_num)

    price = str(seat.get("price", "")).strip() or "∅"
    row_price_to_nums[price][row_label].append(seat_num)

    total_av += 1

st.markdown("### 🪑 Copy-Paste Friendly Available Seat Ranges (this section)")
if total_av == 0:
    st.info("No available seats (status=av) found for this section.")
else:
    lines = []
    for row_label, nums in sorted(row_to_nums.items(), key=lambda x: row_order_key(x[0])):
        for a, b in compress_ranges(nums):
            lines.append(f"{row_label} - {a}" if a == b else f"{row_label} - {a}-{b}")
    st.text_area("Copy/paste:", value=", ".join(lines), height=160)
    st.caption(f"Available seats in this section: {total_av}")

split_by_price = st.checkbox("💷 Also show copy-friendly ranges split by price", value=True)
if split_by_price and total_av > 0:
    st.markdown("### 💷 Copy-Paste Friendly Available Seat Ranges (split by price)")
    for price in sorted(row_price_to_nums.keys(), key=lambda p: (p == "∅", p)):
        title = f"£{price}" if price != "∅" else "(no price)"
        with st.expander(title, expanded=False):
            price_lines = []
            for row_label, nums in sorted(row_price_to_nums[price].items(), key=lambda x: row_order_key(x[0])):
                for a, b in compress_ranges(nums):
                    price_lines.append(f"{row_label} - {a}" if a == b else f"{row_label} - {a}-{b}")
            safe_key = re.sub(r"[^a-zA-Z0-9]+", "_", str(price))[:60]
            st.text_area("Copy/paste:", value=", ".join(price_lines), height=160, key=f"copy_{safe_key}")

st.markdown("---")

# ---------- Inputs (multi-line) ----------

if multi_price_mode:
    group_count = st.number_input("How many price groups?", min_value=2, max_value=50, value=4, step=1)
    groups = []
    for i in range(int(group_count)):
        st.markdown(f"#### Price Group {i+1}")
        rng = st.text_area(
            f"Seat ranges for Group {i+1}",
            placeholder="e.g.\nROW 3 - 88-95\nROW 4 - 10-25",
            key=f"range_{i+1}",
            height=120
        )
        prc = st.text_input(f"Price {i+1}", placeholder="e.g. 45.30", key=f"price_{i+1}")
        groups.append({"range": (rng or "").strip(), "price": (prc or "").strip()})
else:
    seat_range_input = st.text_area(
        "Enter seat ranges",
        placeholder="e.g.\nROW 3 - 88-95\nROW 12 - 101",
        height=120
    )
    price_input = st.text_input(
        "Optional: set price for these seats",
        placeholder="e.g. 45.30"
    )

# ---------- Apply button ----------

if st.button("Apply changes"):
    if multi_price_mode:
        total_changed = 0
        total_price_changed = 0

        for g in groups:
            parsed_ranges = parse_user_ranges(g["range"])
            if not parsed_ranges:
                continue

            changed_status, changed_price = apply_changes(
                seat_data=seat_data,
                section_name=section_choice,
                ranges=parsed_ranges,
                make_available=make_available_bool,
                price_value=g["price"],
                price_only_mode=price_only_mode
            )
            total_changed += changed_status
            total_price_changed += changed_price

        if price_only_mode:
            st.success(f"Updated prices for **{total_price_changed}** seats (availability unchanged).")
        else:
            st.success(f"Updated availability for **{total_changed}** seats, and prices for **{total_price_changed}** seats.")
    else:
        parsed_ranges = parse_user_ranges(seat_range_input)
        if not parsed_ranges:
            st.warning("No valid seat ranges found. Use format like: ROW 3 - 88-95")
        else:
            changed_status, changed_price = apply_changes(
                seat_data=seat_data,
                section_name=section_choice,
                ranges=parsed_ranges,
                make_available=make_available_bool,
                price_value=None if price_only_mode else price_input,
                price_only_mode=price_only_mode
            )
            if price_only_mode:
                st.success(f"Updated prices for **{changed_price}** seats (availability unchanged).")
            else:
                st.success(f"Updated availability for **{changed_status}** seats, and prices for **{changed_price}** seats.")

    # Re-apply auto text blocks after edits (keeps them unavailable even if user pastes them)
    if auto_text_block:
        auto_changed2 = auto_make_text_unavailable(seat_data)
        if auto_changed2 > 0:
            st.info(f"Auto-set **{auto_changed2}** text/placeholder seats to unavailable (status=so).")

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
