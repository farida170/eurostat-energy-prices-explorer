import re
from pathlib import Path

import pandas as pd
import streamlit as st
import altair as alt

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(page_title="EnergyTag — Eurostat Prices Explorer", layout="wide")

APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "Eurostat- Natural gas & electricity prices (2007 onwards).xlsx"
LOGO_FILE = APP_DIR / "energytag.png"

TIME_RE = re.compile(r"^\d{4}-(S1|S2)$")
YEAR_RE = re.compile(r"^\d{4}$")


# -----------------------------
# Auth
# -----------------------------
def get_credentials():
    """
    Uses Streamlit Secrets:
      [auth]
      user = "admin"
      pass = "energytagorg"
    """
    auth = st.secrets.get("auth", {})
    return auth.get("user", ""), auth.get("pass", "")


def login_screen():
    """
    Centered hero welcome + working button.
    Uses Streamlit columns for centering (reliable).
    """
    st.markdown(
        """
        <style>
          /* Hide Streamlit chrome on login */
          header[data-testid="stHeader"] {display:none !important;}
          section[data-testid="stSidebar"] {display:none !important;}
          #MainMenu {visibility:hidden;}
          footer {visibility:hidden;}

          /* Remove padding + force vertical centering */
          .block-container {padding-top: 0 !important; padding-bottom: 0 !important;}
          section.main > div {height: 100vh; display: flex; align-items: center; justify-content: center;}

          /* Hero styles */
          .et-welcome{
            font-size: 46px;
            font-weight: 950;
            letter-spacing: 0.14em;
            margin: 14px 0 8px 0;
            text-align: center;
          }
          .et-sub{
            font-size: 15px;
            opacity: 0.80;
            margin: 0 0 22px 0;
            text-align: center;
          }

          /* Make the primary button look like a CTA */
          div.et-cta > div.stButton > button {
            background: #ff3b3b !important;
            color: #fff !important;
            border: none !important;
            border-radius: 16px !important;
            padding: 12px 22px !important;
            font-weight: 900 !important;
            box-shadow: 0 14px 30px rgba(255,59,59,0.25);
          }

          /* Card styling for the login form area */
          .et-card{
            width: 460px;
            max-width: calc(100vw - 44px);
            margin: 18px auto 0 auto;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.14);
            border-radius: 18px;
            padding: 22px 22px 18px 22px;
            box-shadow: 0 22px 70px rgba(0,0,0,0.55);
            backdrop-filter: blur(12px);
          }
          .et-card-title{
            font-size: 18px;
            font-weight: 850;
            margin: 0 0 10px 0;
          }

          /* Streamlit widget polish */
          .stTextInput > div > div input {border-radius: 12px;}
          .stButton button {border-radius: 12px;}
        </style>
        """,
        unsafe_allow_html=True,
    )

    valid_user, valid_pass = get_credentials()

    if "show_login_form" not in st.session_state:
        st.session_state["show_login_form"] = False

    # True horizontal centering using columns
    left, mid, right = st.columns([1, 2, 1])
    with mid:
        # Logo centered
        if LOGO_FILE.exists():
            st.image(str(LOGO_FILE), width=420)

        st.markdown('<div class="et-welcome">WELCOME!</div>', unsafe_allow_html=True)
        st.markdown('<div class="et-sub">Eurostat energy prices explorer</div>', unsafe_allow_html=True)

        # CTA button (reliable click)
        st.markdown('<div class="et-cta">', unsafe_allow_html=True)
        if not st.session_state["show_login_form"]:
            if st.button("Login", key="login_cta"):
                st.session_state["show_login_form"] = True
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

        # Login form card
        if st.session_state["show_login_form"]:
            st.markdown('<div class="et-card">', unsafe_allow_html=True)
            st.markdown('<div class="et-card-title">Sign in</div>', unsafe_allow_html=True)

            with st.form("login_form", clear_on_submit=False):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in")

            if submitted:
                if u == valid_user and p == valid_pass:
                    st.session_state["authed"] = True
                    st.rerun()
                else:
                    st.error("Invalid username or password.")

            if st.button("Back", key="login_back"):
                st.session_state["show_login_form"] = False
                st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)


if "authed" not in st.session_state:
    st.session_state["authed"] = False

if not st.session_state["authed"]:
    login_screen()
    st.stop()


# -----------------------------
# Data helpers
# -----------------------------
@st.cache_data(show_spinner=False)
def list_sheets(xlsx_path: str):
    return pd.ExcelFile(xlsx_path).sheet_names


@st.cache_data(show_spinner=False)
def load_sheet(xlsx_path: str, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(xlsx_path, sheet_name=sheet_name, dtype=str)


@st.cache_data(show_spinner=False)
def load_codebook_if_exists(xlsx_path: str):
    sheets = list_sheets(xlsx_path)
    for candidate in ["Reference codebook", "Reference_Codebook", "Reference_Codebook "]:
        if candidate in sheets:
            cb = pd.read_excel(xlsx_path, sheet_name=candidate, dtype=str)
            cb.columns = [c.strip() for c in cb.columns]
            for c in ["Dimension", "Code", "Label", "Notes"]:
                if c not in cb.columns:
                    cb[c] = ""
            cb["Dimension"] = cb["Dimension"].fillna("").str.strip()
            cb["Code"] = cb["Code"].fillna("").str.strip()
            cb["Label"] = cb["Label"].fillna("").str.strip()
            cb["Notes"] = cb["Notes"].fillna("").str.strip()
            return candidate, cb
    return None, None


def build_code_maps(codebook: pd.DataFrame):
    label_map = {}
    notes_map = {}
    for dim, sub in codebook.groupby("Dimension"):
        label_map[dim] = dict(zip(sub["Code"], sub["Label"]))
        notes_map[dim] = dict(zip(sub["Code"], sub["Notes"]))
    return label_map, notes_map


def is_time_col(col: str) -> bool:
    c = str(col).strip()
    return bool(TIME_RE.match(c) or YEAR_RE.match(c))


def time_sort_key(t: str):
    t = str(t)
    if "-" in t:
        y, s = t.split("-")
        return (int(y), 1 if s == "S1" else 2)
    return (int(t), 0)


def tidy_from_wide(df: pd.DataFrame) -> pd.DataFrame:
    cols = list(df.columns)
    time_cols = [c for c in cols if is_time_col(c)]
    if not time_cols:
        return df.copy()

    time_to_flag = {}
    for i, c in enumerate(cols):
        if is_time_col(c) and i + 1 < len(cols) and str(cols[i + 1]).lower().startswith("flag"):
            time_to_flag[c] = cols[i + 1]

    dim_cols = [c for c in cols if (c not in time_cols) and (not str(c).lower().startswith("flag"))]
    long = df.melt(id_vars=dim_cols, value_vars=time_cols, var_name="time_period", value_name="value_raw")

    if time_to_flag:
        flag_cols = sorted(set(time_to_flag.values()), key=lambda x: cols.index(x))
        flags_long = df.melt(id_vars=dim_cols, value_vars=flag_cols, var_name="flag_col", value_name="flag_raw")
        flag_to_time = {v: k for k, v in time_to_flag.items()}
        flags_long["time_period"] = flags_long["flag_col"].map(flag_to_time)
        flags_long = flags_long.drop(columns=["flag_col"])
        long = long.merge(flags_long, on=dim_cols + ["time_period"], how="left")
    else:
        long["flag_raw"] = None

    long["value_raw"] = long["value_raw"].astype(str).str.strip()
    long.loc[long["value_raw"].isin([":", "nan", "NaN", ""]), "value_raw"] = None

    def split_inline(v):
        if v is None:
            return (None, None)
        s = str(v).strip()
        m = re.match(r"^([+-]?\d+(?:\.\d+)?)(?:\s*\(?([A-Za-z]+)\)?)?$", s)
        if m:
            return (m.group(1), m.group(2))
        return (s, None)

    parsed = long["value_raw"].apply(split_inline)
    long["value_num_str"] = [p[0] for p in parsed]
    long["flag_inline"] = [p[1] for p in parsed]

    long["flag"] = long["flag_raw"]
    long.loc[(long["flag"].isna()) | (long["flag"].astype(str).str.strip() == ""), "flag"] = long["flag_inline"]

    long["value"] = pd.to_numeric(long["value_num_str"], errors="coerce")
    out = long.drop(columns=["value_raw", "flag_raw", "value_num_str", "flag_inline"])
    return out


FRIENDLY_COLS = {
    "time_period": "Time period",
    "value": "Value",
    "flag": "Flag",
    "geo": "Country / region",
    "siec": "Energy carrier",
    "nrg_cons": "Consumption band",
    "nrg_prc": "Price component",
    "tax": "Tax treatment",
    "currency": "Currency basis",
    "unit": "Unit",
    "freq": "Frequency",
    "customer": "Customer type",
}
LABEL_SUFFIX = " (label)"


def apply_friendly_headers(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    new_cols = {}
    for c in out.columns:
        if c.endswith("_label"):
            base = c.replace("_label", "")
            new_cols[c] = f"{FRIENDLY_COLS.get(base, base)}{LABEL_SUFFIX}"
        else:
            new_cols[c] = FRIENDLY_COLS.get(c, c)
    return out.rename(columns=new_cols)


FULL_SHEET_TITLES = [
    "Gas prices for household consumers - bi-annual data",
    "Gas prices for non-household consumers - bi-annual data",
    "Electricity prices for household consumers - bi-annual data",
    "Electricity prices for non-household consumers - bi-annual data",
    "Household consumption volumes of gas by consumption bands",
    "Non-household consumption volumes of gas by consumption bands",
    "Household consumption volumes of electricity by consumption bands",
    "Non-household consumption volumes of electricity by consumption bands",
    "Gas prices components for household consumers - annual data",
    "Gas prices components for non-household consumers - annual data",
    "Electricity prices components for non-household consumers - annual data",
    "Electricity prices components for household consumers - annual data",
    "Share for transmission and distribution in the network cost for gas and electricity - annual data",
]


def build_sheet_title_maps(actual_sheets, full_titles):
    actual_set = set(actual_sheets)
    title_to_sheet = {}
    for t in full_titles:
        key = t[:31]
        if key in actual_set:
            title_to_sheet[t] = key
        else:
            cand = [s for s in actual_sheets if s.startswith(key[:18])]
            if cand:
                title_to_sheet[t] = cand[0]
    return title_to_sheet


# -----------------------------
# Load workbook
# -----------------------------
if not DATA_FILE.exists():
    st.error(f"Missing data file: {DATA_FILE.name}. Make sure it’s in the repo.")
    st.stop()

sheets = list_sheets(str(DATA_FILE))
codebook_sheet, codebook = load_codebook_if_exists(str(DATA_FILE))
data_sheets = [s for s in sheets if s != codebook_sheet]

label_map, notes_map = ({}, {})
if codebook is not None:
    label_map, notes_map = build_code_maps(codebook)

title_to_sheet = build_sheet_title_maps(data_sheets, FULL_SHEET_TITLES)

# -----------------------------
# Sidebar
# -----------------------------
st.sidebar.markdown("##")
if LOGO_FILE.exists():
    st.sidebar.image(str(LOGO_FILE), width=180)

st.sidebar.markdown("### Dataset")
display_title = st.sidebar.selectbox("Choose sheet", FULL_SHEET_TITLES, index=0)
sheet = title_to_sheet.get(display_title, data_sheets[0])

st.sidebar.markdown("---")
show_labels = st.sidebar.toggle("Show labels next to codes", value=True)
view_mode = st.sidebar.radio("View", ["Table", "Charts"], index=0)

st.sidebar.markdown("---")
st.sidebar.markdown("### Definitions")
if codebook is None:
    st.sidebar.info("No reference codebook sheet found.")
else:
    dim_pick = st.sidebar.selectbox("Dimension", sorted(codebook["Dimension"].unique().tolist()))
    code_pick = st.sidebar.selectbox("Code", sorted(codebook.loc[codebook["Dimension"] == dim_pick, "Code"].unique().tolist()))
    st.sidebar.write("**Label:**", label_map.get(dim_pick, {}).get(code_pick, ""))
    notes = notes_map.get(dim_pick, {}).get(code_pick, "")
    if notes:
        st.sidebar.write("**Notes:**", notes)

st.sidebar.markdown("---")
if st.sidebar.button("Logout"):
    st.session_state["authed"] = False
    st.rerun()

# -----------------------------
# Header
# -----------------------------
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.0rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

h1, h2 = st.columns([6, 1], vertical_alignment="center")
with h1:
    st.markdown("## Eurostat — Natural gas & electricity prices (2007 onwards)")
    st.caption("Filter, chart, and export tables across datasets.")
with h2:
    if LOGO_FILE.exists():
        st.image(str(LOGO_FILE), width=150)

st.markdown(f"# {display_title}")

# -----------------------------
# Load + tidy
# -----------------------------
raw = load_sheet(str(DATA_FILE), sheet)
tidy = tidy_from_wide(raw)

if show_labels and codebook is not None:
    for c in list(tidy.columns):
        if c in ["time_period", "value", "flag"]:
            continue
        if c in label_map:
            tidy[f"{c}_label"] = tidy[c].map(label_map[c]).fillna("")

times = sorted(tidy["time_period"].dropna().astype(str).unique().tolist(), key=time_sort_key)
reserved = {"time_period", "value", "flag"}
dim_cols = [c for c in tidy.columns if c not in reserved and not c.endswith("_label")]

# -----------------------------
# Filters (default = ALL data)
# -----------------------------
def ss_init(key, default):
    if key not in st.session_state:
        st.session_state[key] = default


ss_init("sel_time", [])
ss_init("sel_geo", [])

with st.expander("Filters", expanded=True):
    b1, b2, b3 = st.columns([1.2, 1.0, 2.8])
    with b1:
        apply_clicked = st.button("Apply filters", type="primary")
    with b2:
        clear_clicked = st.button("Clear")
    with b3:
        auto_apply = st.toggle("Auto-apply", value=False)

    if clear_clicked:
        for k in list(st.session_state.keys()):
            if k.startswith("sel_"):
                del st.session_state[k]
        st.rerun()

    c1, c2 = st.columns([2, 3], gap="large")
    with c1:
        time_sel = st.multiselect("Time period", times, default=st.session_state.get("sel_time", []), key="sel_time")
    with c2:
        geo_sel = []
        if "geo" in tidy.columns:
            geos = sorted(tidy["geo"].dropna().astype(str).unique().tolist())
            geo_sel = st.multiselect("Country / region (geo)", geos, default=st.session_state.get("sel_geo", []), key="sel_geo")
            if not geo_sel:
                st.caption("All countries")

    other_cols = [c for c in dim_cols if c != "geo"]
    other_filters = {}
    if other_cols:
        grid = st.columns(3, gap="large")
        for i, colname in enumerate(other_cols):
            vals = sorted(tidy[colname].dropna().astype(str).unique().tolist())
            label_col = f"{colname}_label" if show_labels and f"{colname}_label" in tidy.columns else None

            with grid[i % 3]:
                ui_label = FRIENDLY_COLS.get(colname, colname)
                if label_col:
                    display = []
                    for v in vals:
                        lab = tidy.loc[tidy[colname].astype(str) == v, label_col].dropna().astype(str).unique()
                        lab = lab[0] if len(lab) else ""
                        display.append(f"{v} — {lab}" if lab else v)
                    display_to_code = dict(zip(display, vals))
                    chosen_disp = st.multiselect(ui_label, display, default=st.session_state.get(f"sel_{colname}", []), key=f"sel_{colname}")
                    other_filters[colname] = [display_to_code[x] for x in chosen_disp] if chosen_disp else []
                else:
                    chosen = st.multiselect(ui_label, vals, default=st.session_state.get(f"sel_{colname}", []), key=f"sel_{colname}")
                    other_filters[colname] = chosen if chosen else []

apply_now = auto_apply or apply_clicked

filt = tidy.copy()
if apply_now:
    if time_sel:
        filt = filt[filt["time_period"].astype(str).isin([str(x) for x in time_sel])]
    if "geo" in filt.columns and geo_sel:
        filt = filt[filt["geo"].astype(str).isin([str(x) for x in geo_sel])]
    for colname, chosen in other_filters.items():
        if chosen:
            filt = filt[filt[colname].astype(str).isin([str(x) for x in chosen])]

# -----------------------------
# Summary + Download
# -----------------------------
m1, m2, m3, m4 = st.columns(4)
m1.metric("Rows", f"{len(filt):,}")
m2.metric("Countries", f"{filt['geo'].nunique():,}" if "geo" in filt.columns else "—")
m3.metric("Time periods", f"{filt['time_period'].nunique():,}")
m4.metric("Flags", f"{(filt['flag'].notna() & (filt['flag'].astype(str).str.strip()!='')).sum():,}" if "flag" in filt.columns else "—")

st.download_button(
    "Download CSV (current view)",
    data=filt.to_csv(index=False).encode("utf-8"),
    file_name=f"{display_title}.csv",
    mime="text/csv",
)

display_df = apply_friendly_headers(filt)

# -----------------------------
# Table / Charts
# -----------------------------
if view_mode == "Table":
    st.markdown("### Results")
    st.dataframe(display_df, use_container_width=True, height=620)
else:
    st.markdown("### Charts")
    if filt.empty:
        st.info("No data after filters.")
    else:
        possible_group = [c for c in ["geo", "tax", "currency", "nrg_cons", "customer", "siec", "unit", "nrg_prc"] if c in filt.columns]
        group_col = st.selectbox("Group / color by", possible_group, index=0 if possible_group else 0)

        chart_df = filt.copy()
        chart_df["time_period"] = chart_df["time_period"].astype(str)

        base = (
            alt.Chart(chart_df)
            .encode(
                x=alt.X("time_period:N", sort=times, title="Time period"),
                y=alt.Y("value:Q", title="Value"),
                tooltip=[
                    alt.Tooltip("time_period:N", title="Time"),
                    alt.Tooltip("value:Q", title="Value"),
                    alt.Tooltip("flag:N", title="Flag"),
                    alt.Tooltip(f"{group_col}:N", title=FRIENDLY_COLS.get(group_col, group_col)),
                ],
            )
            .properties(height=420)
        )

        line = base.mark_line(point=True).encode(
            color=alt.Color(f"{group_col}:N", title=FRIENDLY_COLS.get(group_col, group_col))
        )

        st.altair_chart(
            line.configure_view(strokeWidth=0)
                .configure_axis(grid=True, gridColor="#E6E6E6", domain=False, tickColor="#999999",
                                labelColor="#444444", titleColor="#444444")
                .configure_legend(titleColor="#444444", labelColor="#444444")
                .configure_title(color="#222222"),
            use_container_width=True,
        )
