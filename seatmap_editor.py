import streamlit as st
import json, re
from collections import defaultdict

# =========================
#  🎭 Seat Map Availability Editor
# =========================
st.set_page_config(page_title="🎭 Seat Map Availability Editor", layout="wide")
st.title("🎭 Seat Map Availability Editor")

# -------------------------
# Your JSON shape helpers
# -------------------------

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

def norm(s: str) -> str:
    return (s or "").strip().lower()

# -------------------------
# Seat parsing
# -------------------------

def parse_seat_number_field(number_field: str):
    """
    Expected for real seats:
      "ROW 3 - 88"
      "ROW 12 - 101"
    Returns (row_label, seat_num_int), like ("ROW 3", 88)
    """
    s = (number_field or "").strip()
    m = re.match(r"^(ROW\s*\d+)\s*-\s*(\d+)$", s, re.IGNORECASE)
    if not m:
        return None
    row = m.group(1).upper().replace("  ", " ").strip()
    num = int(m.group(2))
    return row, num

def row_order_key(row_label: str):
    s = (row_label or "").upper()
    m = re.match(r"^ROW\s*(\d+)$", s)
    if m:
        return (0, int(m.group(1)))
    return (1, s)

def compress_ranges(nums):
    nums = sorted(set(nums))
    if not nums:
        return []
    out = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
        else:
            out.append((start, prev))
            start = prev = n
    out.append((start, prev))
    return out

# -------------------------
# Always-on auto-unavailable
# -------------------------

TEXT_BLOCK_KEYWORDS = ["PILLAR", "PILAR", "EMPTY", "BLANK", "SPACE"]

def is_text_placeholder_seat(seat: dict) -> bool:
    """
    If it smells like a label block / placeholder, we force it unavailable.
    Rules:
    - If any common text fields contain PILLAR/PILAR/EMPTY/BLANK/SPACE
    - OR if it has a 'number' string but does NOT match "ROW X - N"
      (this catches non-seat labels)
    """
    # Keyword scan
    candidates = []
    for k in ["number", "label", "text", "name", "type", "seatLabel", "seat_label"]:
        v = seat.get(k)
        if isinstance(v, str) and v.strip():
            candidates.append(v.strip())

    joined = " | ".join(candidates).upper()
    if any(kw in joined for kw in TEXT_BLOCK_KEYWORDS):
        return True

    # If number exists but isn't a normal seat format, treat as text block
    num_field = seat.get("number")
    if isinstance(num_field, str) and num_field.strip():
        if parse_seat_number_field(num_field) is None:
            return True

    return False

def auto_make_text_unavailable(seat_data):
    """
    Always-on: any placeholder seat becomes unavailable.
    Uses status='so' to match your file style.
    Returns number of seats changed.
    """
    changed = 0
    for seat, _sec in iter_seats_with_section(seat_data):
        if is_text_placeholder_seat(seat):
            if norm(seat.get("status", "")) != "so":
                seat["status"] = "so"
                changed += 1
    return changed

# -------------------------
# UI
# -------------------------

st.markdown("## Upload")
uploaded = st.file_uploader("Upload your seatmap JSON file", type=["json"])

seat_data = None
if uploaded:
    seat_data = safe_load_json(uploaded)

if not seat_data:
    st.info("Upload a seatmap JSON file to begin.")
    st.stop()

# Always enforce placeholders unavailable
auto_changed = auto_make_text_unavailable(seat_data)
if auto_changed:
    st.info(f"Auto-set **{auto_changed}** placeholder/text seats to unavailable (status=so).")

# -------------------------
# Detect AV seats and group by price (no sections UI)
# -------------------------

# price -> row_label -> [nums]
price_row_map = defaultdict(lambda: defaultdict(list))

# overall (all prices)
overall_row_map = defaultdict(list)

# optional: keep section in the line output so you can still tell areas apart
# section -> price -> row -> nums
section_price_row_map = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

av_total = 0
av_prices = set()

for seat, section in iter_seats_with_section(seat_data):
    if norm(seat.get("status", "")) != "av":
        continue

    parsed = parse_seat_number_field(seat.get("number", ""))
    if not parsed:
        continue

    row_label, seat_num = parsed
    price = str(seat.get("price", "")).strip() or "∅"

    av_total += 1
    av_prices.add(price)

    overall_row_map[row_label].append(seat_num)
    price_row_map[price][row_label].append(seat_num)
    section_price_row_map[section][price][row_label].append(seat_num)

st.markdown("---")
st.markdown("## Copy-friendly seat ranges (auto-detected)")

if av_total == 0:
    st.warning("I couldn’t find any seats with status = av in this file (after auto-blocking placeholders).")
else:
    st.caption(f"Detected **{av_total}** available seats across **{len(av_prices)}** prices.")

    # Overall (all AV seats)
    overall_lines = []
    for row_label, nums in sorted(overall_row_map.items(), key=lambda x: row_order_key(x[0])):
        for a, b in compress_ranges(nums):
            overall_lines.append(f"{row_label} - {a}" if a == b else f"{row_label} - {a}-{b}")

    st.markdown("### 🪑 All AV seats (all prices)")
    st.text_area("Copy/paste:", value=", ".join(overall_lines), height=160)

    # Split by price (global, no sections in UI)
    st.markdown("### 💷 AV seats split by price")
    for price in sorted(price_row_map.keys(), key=lambda p: (p == "∅", p)):
        rows = price_row_map[price]
        lines = []
        seat_count = 0

        for row_label, nums in rows.items():
            seat_count += len(set(nums))

        for row_label, nums in sorted(rows.items(), key=lambda x: row_order_key(x[0])):
            for a, b in compress_ranges(nums):
                lines.append(f"{row_label} - {a}" if a == b else f"{row_label} - {a}-{b}")

        title = f"£{price}" if price != "∅" else "(no price)"
        with st.expander(f"{title} ({seat_count} AV seats)", expanded=False):
            safe_key = re.sub(r"[^a-zA-Z0-9]+", "_", str(price))[:60]
            st.text_area("Copy/paste:", value=", ".join(lines), height=160, key=f"copy_price_{safe_key}")

    # Optional: still show by section+price (without selecting sections)
    show_by_section = st.checkbox("Show split by section too (optional)", value=False)
    if show_by_section:
        st.markdown("### 🎟️ AV seats split by section and price")
        for section in sorted(section_price_row_map.keys(), key=lambda s: (s or "").lower()):
            with st.expander(section or "(no section name)", expanded=False):
                for price in sorted(section_price_row_map[section].keys(), key=lambda p: (p == "∅", p)):
                    rows = section_price_row_map[section][price]
                    lines = []
                    seat_count = 0
                    for row_label, nums in rows.items():
                        seat_count += len(set(nums))

                    for row_label, nums in sorted(rows.items(), key=lambda x: row_order_key(x[0])):
                        for a, b in compress_ranges(nums):
                            lines.append(f"{row_label} - {a}" if a == b else f"{row_label} - {a}-{b}")

                    label = f"£{price}" if price != "∅" else "(no price)"
                    safe_key = re.sub(r"[^a-zA-Z0-9]+", "_", f"{section}_{price}")[:80]
                    st.text_area(
                        f"{label} ({seat_count} seats)",
                        value=", ".join(lines),
                        height=140,
                        key=f"copy_sec_price_{safe_key}"
                    )

# -------------------------
# Download
# -------------------------
st.markdown("---")
st.markdown("## Download updated JSON")
st.download_button(
    "Download JSON",
    data=json.dumps(seat_data, indent=2),
    file_name="seatmap_updated.json",
    mime="application/json"
)


