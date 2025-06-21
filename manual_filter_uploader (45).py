import streamlit as st
import os, unicodedata, re
from itertools import product, combinations

# ==============================
# Helper functions for parsing manual filters
# ==============================
def strip_prefix(raw_name: str) -> str:
    # Remove leading numbering like "1. ", "10) ", etc.
    return re.sub(r'^\s*\d+[\.\)]\s*', '', raw_name).strip()

def normalize_name(raw_name: str) -> str:
    s = unicodedata.normalize('NFKC', raw_name)
    # Replace common unicode symbols
    s = s.replace('≥', '>=').replace('≤', '<=').replace('\u2265', '>=').replace('\u2264', '<=')
    s = s.replace('→', '->').replace('\u2192', '->')
    s = s.replace('–', '-').replace('—', '-')
    # Remove zero-width or NBSP
    s = s.replace('\u200B', '').replace('\u00A0', ' ')
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def parse_manual_filters_txt(raw_text: str):
    """
    Parse raw_text into filter entries.
    Each filter is expected to have:
      <Filter Name>\n
      Type: ...\n
      Logic: ...\n
      Action: ...
    But we scan line-by-line: any line not starting with Type:/Logic:/Action: is a new name.
    Returns: (entries, skipped_blocks)
      entries: list of dicts {'name':..., 'type':..., 'logic':..., 'action':...}
      skipped_blocks: list of raw text for blocks missing name
    """
    entries = []
    skipped = []
    # Normalize line endings
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    current = None
    for raw_ln in lines:
        ln = raw_ln.strip()
        if not ln:
            # Blank line: finalize current
            if current:
                if current.get('name'):
                    entries.append(current)
                else:
                    skipped.append(current)
                current = None
            continue
        norm_ln = unicodedata.normalize('NFKC', ln)
        low = norm_ln.lower()
        # Prefix lines
        if low.startswith('type:'):
            if current is None:
                current = {'name': '', 'type': '', 'logic': '', 'action': ''}
            current['type'] = norm_ln.split(':', 1)[1].strip()
        elif low.startswith('logic:'):
            if current is None:
                current = {'name': '', 'type': '', 'logic': '', 'action': ''}
            after = norm_ln.split(':', 1)[1].strip()
            if after.lower().startswith('logic:'):
                after = after.split(':', 1)[1].strip()
            current['logic'] = after
        elif low.startswith('action:'):
            if current is None:
                current = {'name': '', 'type': '', 'logic': '', 'action': ''}
            current['action'] = norm_ln.split(':', 1)[1].strip()
        else:
            # Name line
            if current:
                if current.get('name'):
                    entries.append(current)
                else:
                    skipped.append(current)
            clean = strip_prefix(norm_ln)
            name_norm = normalize_name(clean)
            current = {'name': name_norm, 'type': '', 'logic': '', 'action': ''}
    # Finalize last
    if current:
        if current.get('name'):
            entries.append(current)
        else:
            skipped.append(current)
    return entries, skipped

# ==============================
# Example filter application functions (to extend as needed)
# ==============================
def seed_sum_matches_condition(seed_sum: int, condition_str: str) -> bool:
    s = condition_str.strip()
    # ≤ or <=
    m = re.match(r'[≤<=]\s*(\d+)', s)
    if m:
        num = int(m.group(1)); return seed_sum <= num
    # ≥ or >= or "or higher"
    m = re.match(r'(?:≥|>=)?\s*(\d+)\s*or\s*higher', s, re.IGNORECASE)
    if m:
        num = int(m.group(1)); return seed_sum >= num
    # range low–high or low-high
    m = re.match(r'(\d+)\s*[–-]\s*(\d+)', s)
    if m:
        low, high = int(m.group(1)), int(m.group(2)); return low <= seed_sum <= high
    # exact
    if s.isdigit(): return seed_sum == int(s)
    return False

def apply_sum_range_filter(combos, min_sum, max_sum):
    keep = [c for c in combos if min_sum <= sum(int(d) for d in c) <= max_sum]
    removed = [c for c in combos if c not in keep]
    return keep, removed

def apply_keep_sum_range_if_seed_sum(combos, seed_sum, min_sum, max_sum, seed_condition_str):
    if seed_sum_matches_condition(seed_sum, seed_condition_str):
        return apply_sum_range_filter(combos, min_sum, max_sum)
    else:
        return combos, []

def apply_conditional_seed_contains(combos, seed_digits, seed_digit, required_winners):
    if seed_digit in seed_digits:
        keep = []
        removed = []
        for c in combos:
            if any(str(d) in c for d in required_winners):
                keep.append(c)
            else:
                removed.append(c)
        return keep, removed
    else:
        return combos, []

# ==============================
# Generate combinations (placeholder)
# ==============================
def generate_combinations(seed, method="2-digit pair"):
    all_digits = '0123456789'
    combos = set()
    seed_str = str(seed)
    if method == "1-digit":
        for d in seed_str:
            for p in product(all_digits, repeat=4):
                combo = ''.join(sorted(d + ''.join(p)))
                combos.add(combo)
    else:
        pairs = set(''.join(sorted((seed_str[i], seed_str[j])))
                    for i in range(len(seed_str)) for j in range(i+1, len(seed_str)))
        for pair in pairs:
            for p in product(all_digits, repeat=3):
                combo = ''.join(sorted(pair + ''.join(p)))
                combos.add(combo)
    return sorted(combos)

# ==============================
# Streamlit App
# ==============================
st.title("DC-5 Midday Blind Predictor with Combined Filters")
# Sidebar inputs
seed = st.sidebar.text_input("5-digit seed:")
hot_digits = [d for d in st.sidebar.text_input("Hot digits (comma-separated):").replace(' ', '').split(',') if d]
cold_digits = [d for d in st.sidebar.text_input("Cold digits (comma-separated):").replace(' ', '').split(',') if d]
due_digits = [d for d in st.sidebar.text_input("Due digits (comma-separated):").replace(' ', '').split(',') if d]
method = st.sidebar.selectbox("Generation Method:", ["1-digit", "2-digit pair"]) 
enable_trap = st.sidebar.checkbox("Enable Trap V3 Ranking")
# Upload or use combined file or fallbacks
uploaded = st.sidebar.file_uploader("Upload manual filters file (TXT)", type=['txt'])
raw_manual = None
# Try uploaded
if uploaded is not None:
    try:
        raw_manual = uploaded.read().decode('utf-8', errors='ignore')
        st.sidebar.success("Loaded uploaded manual filters file.")
    except Exception as e:
        st.sidebar.error(f"Failed reading uploaded file: {e}")
else:
    # Search for possible filter files in cwd
    candidates = ["manual_filters_combined.txt", "manual_filters_full.txt", "manual_filters_degrouped.txt", "working_108_filters.txt"]
    found = []
    for fname in candidates:
        if os.path.exists(fname):
            found.append(fname)
    if len(found) > 1:
        # Combine contents
        contents = []
        for fname in found:
            try:
                txt = open(fname, 'r', encoding='utf-8').read()
                contents.append(txt)
                st.sidebar.info(f"Loaded manual filters from {fname}")
            except Exception as e:
                st.sidebar.error(f"Failed reading {fname}: {e}")
        raw_manual = "\n\n".join(contents)
    elif len(found) == 1:
        fname = found[0]
        try:
            raw_manual = open(fname, 'r', encoding='utf-8').read()
            st.sidebar.info(f"Loaded manual filters from {fname}")
        except Exception as e:
            st.sidebar.error(f"Failed reading {fname}: {e}")
    else:
        st.sidebar.warning("No manual filter file found (looked for combined/full/degrouped/working_108). Upload a TXT.")

parsed_entries = []
if raw_manual:
    parsed_entries, skipped = parse_manual_filters_txt(raw_manual)
    st.write(f"Parsed {len(parsed_entries)} manual filter blocks")
    if skipped:
        st.warning(f"{len(skipped)} blocks skipped due to missing name. Expand to view.")
        with st.expander("Skipped blocks"):
            for sb in skipped:
                st.code(sb[:300] + ("..." if len(sb)>300 else ""))
    if st.sidebar.checkbox("Show normalized filter names for debugging"):
        for pf in parsed_entries:
            raw_name = pf['name']
            label = strip_prefix(raw_name)
            norm = normalize_name(label).lower()
            st.write(f"DEBUG: '{raw_name}' -> '{norm}'")
else:
    st.write("No manual filters loaded.")

# When seed provided, generate combos
session_pool = []
if seed:
    combos_initial = generate_combinations(seed, method)
    session_pool = combos_initial.copy()
    st.write(f"Generated {len(combos_initial)} combos before manual filters.")
    # Apply selected manual filters
    for idx, pf in enumerate(parsed_entries):
        label = strip_prefix(pf['name'])
        key = f"filter_{idx}"
        checked = st.sidebar.checkbox(label, key=key)
        if checked:
            logic = pf.get('logic', '')
            # sum-range elimination: "Eliminate if sum <X or >Y"
            m_sum = re.search(r'sum\s*<\s*(\d+)\s*or\s*>\s*(\d+)', logic, re.IGNORECASE)
            if m_sum:
                low, high = int(m_sum.group(1)), int(m_sum.group(2))
                keep, removed = apply_sum_range_filter(session_pool, low, high)
                session_pool = keep
                st.write(f"Filter '{label}' removed {len(removed)} combos.")
                continue
            # keep-sum-range if seed-sum condition
            m_keep = re.search(r'between\s*(\d+)\s*and\s*(\d+).*if the seed sum is\s*([≤>=\d\s\-orhigher–]+)', logic, re.IGNORECASE)
            if m_keep:
                low, high = int(m_keep.group(1)), int(m_keep.group(2))
                seed_cond = m_keep.group(3).strip()
                seed_sum = sum(int(d) for d in seed)
                keep, removed = apply_keep_sum_range_if_seed_sum(session_pool, seed_sum, low, high, seed_cond)
                session_pool = keep
                st.write(f"Filter '{label}' removed {len(removed)} combos.")
                continue
            # conditional seed contains
            m_cond = re.search(r'seed contains\s*(\d+)\s*.*contains neither\s*([\d,\s]+)', logic, re.IGNORECASE)
            if m_cond:
                sd = int(m_cond.group(1))
                reqs = [int(x) for x in re.findall(r'(\d)', m_cond.group(2))]
                seed_digits = [int(d) for d in seed]
                keep, removed = apply_conditional_seed_contains(session_pool, seed_digits, sd, reqs)
                session_pool = keep
                st.write(f"Filter '{label}' removed {len(removed)} combos.")
                continue
            st.warning(f"Could not automatically apply filter logic for: '{label}'")
    st.write(f"**Remaining combos after manual filters:** {len(session_pool)}")
    with st.expander("Show remaining combinations"):
        for c in session_pool:
            st.write(c)

# Trap V3 Ranking
if enable_trap and seed and session_pool:
    try:
        import dc5_trapv3_model as trap_model
        ranked = trap_model.rank_combinations(session_pool, str(seed))
        st.write("## Trap V3 Ranking")
        st.write("Top combos:")
        for c in ranked[:20]: st.write(c)
        if len(ranked) > 20:
            with st.expander("Show all ranked combos"):
                for c in ranked: st.write(c)
    except Exception as e:
        st.error(f"Trap V3 ranking failed: {e}")
