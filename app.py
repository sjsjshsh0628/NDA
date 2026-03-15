import streamlit as st
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import json
import os
import io
import yaml
import calendar
from yaml.loader import SafeLoader
from typing import Optional
from datetime import date, timedelta

st.set_page_config(
    page_title="일간 마케팅 대시보드",
    page_icon="📊",
    layout="wide",
)

# ─────────────────────────────────────────────
# 인증
# ─────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

with open(CONFIG_PATH) as f:
    config = yaml.load(f, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"],
)

try:
    authenticator.login()
except Exception as e:
    st.error(e)

if st.session_state.get("authentication_status") is False:
    st.error("아이디 또는 비밀번호가 틀렸습니다.")
    st.stop()
elif st.session_state.get("authentication_status") is None:
    st.warning("로그인이 필요합니다.")
    st.stop()

# ─────────────────────────────────────────────
# DB 초기화
# ─────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            name TEXT PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS member_data (
            date TEXT PRIMARY KEY,
            nv_cust INTEGER,
            nv_rev INTEGER,
            js_mem INTEGER,
            js_rev INTEGER
        );
        CREATE TABLE IF NOT EXISTS ads_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_json TEXT,
            uploaded_at TEXT
        );
    """)
    conn.commit()
    conn.close()


init_db()

# ─────────────────────────────────────────────
# 헬퍼 함수 — DB
# ─────────────────────────────────────────────


def load_products():
    conn = get_db()
    rows = conn.execute("SELECT name FROM products ORDER BY name").fetchall()
    conn.close()
    return [r[0] for r in rows]


def save_products(lst):
    conn = get_db()
    conn.execute("DELETE FROM products")
    conn.executemany("INSERT OR IGNORE INTO products (name) VALUES (?)", [(p,) for p in lst])
    conn.commit()
    conn.close()


def load_member_data():
    conn = get_db()
    rows = conn.execute("SELECT date, nv_cust, nv_rev, js_mem, js_rev FROM member_data").fetchall()
    conn.close()
    return {r[0]: {"nv_cust": r[1], "nv_rev": r[2], "js_mem": r[3], "js_rev": r[4]} for r in rows}


def save_member_day(d_str, nv_cust, nv_rev, js_mem, js_rev):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO member_data (date, nv_cust, nv_rev, js_mem, js_rev) VALUES (?,?,?,?,?)",
        (d_str, nv_cust, nv_rev, js_mem, js_rev),
    )
    conn.commit()
    conn.close()


def save_ads_data(df):
    conn = get_db()
    conn.execute("DELETE FROM ads_data")
    conn.execute("INSERT INTO ads_data (data_json) VALUES (?)", (df.to_json(force_ascii=False),))
    conn.commit()
    conn.close()


def load_ads_data():
    conn = get_db()
    row = conn.execute("SELECT data_json FROM ads_data ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        return pd.read_json(io.StringIO(row[0]))
    return None


def safe_divide(a, b):
    try:
        a = float(a)
        b = float(b)
        if b == 0:
            return 0
        return a / b
    except (ValueError, TypeError):
        return 0


def find_col(df, *keywords, exclude=None):
    for c in df.columns:
        cs = str(c)
        if all(k in cs for k in keywords):
            if exclude and any(e in cs for e in exclude):
                continue
            return c
    return None


def load_file(uploaded) -> Optional[pd.DataFrame]:
    if uploaded is None:
        return None
    try:
        if uploaded.name.endswith((".xlsx", ".xls")):
            return pd.read_excel(uploaded)
        else:
            return pd.read_csv(uploaded)
    except Exception as e:
        st.error(f"파일 로드 오류: {e}")
        return None


def color_delta(val):
    try:
        v = float(str(val).replace(",", "").replace("%", "").replace("+", ""))
        if v > 0:
            return "color: #16a34a; font-weight: bold"
        elif v < 0:
            return "color: #dc2626; font-weight: bold"
    except Exception:
        pass
    return ""


def fmt_number(n):
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def fmt_money(n):
    try:
        return f"₩{int(n):,}"
    except Exception:
        return str(n)


def fmt_pct(n, decimals=1):
    try:
        return f"{float(n):.{decimals}f}%"
    except Exception:
        return str(n)


def get_week_range(year, month, week):
    first_day = date(year, month, 1)
    first_sunday = first_day - timedelta(days=(first_day.weekday() + 1) % 7)
    week_start = first_sunday + timedelta(weeks=week - 1)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def get_max_weeks(year, month):
    _, last_day = calendar.monthrange(year, month)
    last_date = date(year, month, last_day)
    first_date = date(year, month, 1)
    first_sunday = first_date - timedelta(days=(first_date.weekday() + 1) % 7)
    weeks = ((last_date - first_sunday).days // 7) + 1
    return max(1, weeks)


# ─────────────────────────────────────────────
# session_state 초기화
# ─────────────────────────────────────────────

if "member_data" not in st.session_state:
    st.session_state.member_data = load_member_data()
if "ads_raw_data" not in st.session_state:
    st.session_state.ads_raw_data = load_ads_data()
if "members_confirmed" not in st.session_state:
    st.session_state.members_confirmed = bool(st.session_state.member_data)
if "ads_confirmed" not in st.session_state:
    st.session_state.ads_confirmed = st.session_state.ads_raw_data is not None

today = date.today()
if "filter_mode" not in st.session_state:
    st.session_state.filter_mode = "전체"
if "filter_year" not in st.session_state:
    st.session_state.filter_year = today.year
if "filter_month" not in st.session_state:
    st.session_state.filter_month = today.month
if "filter_week" not in st.session_state:
    st.session_state.filter_week = 1

# 날짜 모드 session_state
if "member_date_mode" not in st.session_state:
    st.session_state.member_date_mode = "오늘"
if "member_date_start" not in st.session_state:
    st.session_state.member_date_start = today
if "member_date_end" not in st.session_state:
    st.session_state.member_date_end = today
if "ads_date_mode" not in st.session_state:
    st.session_state.ads_date_mode = "오늘"
if "ads_date_start" not in st.session_state:
    st.session_state.ads_date_start = today
if "ads_date_end" not in st.session_state:
    st.session_state.ads_date_end = today

# 상품 관련
if "selected_product" not in st.session_state:
    st.session_state.selected_product = None
if "adding_product" not in st.session_state:
    st.session_state.adding_product = False
if "product_list" not in st.session_state:
    st.session_state.product_list = load_products()


# ─────────────────────────────────────────────
# 사이드바 — 데이터 입력
# ─────────────────────────────────────────────

with st.sidebar:
    st.caption(f"👤 {st.session_state.get('name', '')}")
    authenticator.logout("로그아웃", "sidebar")
    st.divider()
    st.header("📥 데이터 입력")

    direct_input_mode = False
    df_members_file = None

    # ── 입력1: 회원 현황 ──
    st.subheader("입력1 — 회원 현황")
    mode_members = st.radio(
        "입력 방식",
        ["직접 입력", "파일 업로드", "샘플"],
        horizontal=True,
        key="mode_members",
    )

    if mode_members == "직접 입력":
        direct_input_mode = True

        # 날짜 선택: 오늘 / 직접 입력
        def cb_member_date_today():
            st.session_state.member_date_mode = "오늘"
            st.session_state.member_date_start = today
            st.session_state.member_date_end = today

        def cb_member_date_custom():
            st.session_state.member_date_mode = "직접 입력"

        mc1, mc2 = st.columns(2)
        with mc1:
            st.button("오늘", key="btn_member_date_today", use_container_width=True, on_click=cb_member_date_today,
                       type="primary" if st.session_state.member_date_mode == "오늘" else "secondary")
        with mc2:
            st.button("직접 입력", key="btn_member_date_custom", use_container_width=True, on_click=cb_member_date_custom,
                       type="primary" if st.session_state.member_date_mode == "직접 입력" else "secondary")

        if st.session_state.member_date_mode == "직접 입력":
            st.session_state.member_date_start = st.date_input("시작일자", value=st.session_state.member_date_start, key="member_start")
            st.session_state.member_date_end = st.date_input("종료일자", value=st.session_state.member_date_end, key="member_end")

        st.markdown("**네이버**")
        nv_cust_input = st.number_input("관심고객수", min_value=0, step=1, value=0, key="nv_cust")
        nv_rev_input = st.number_input("매출", min_value=0, step=1, value=0, key="nv_rev")

        st.markdown("**자사몰**")
        js_mem_input = st.number_input("회원수", min_value=0, step=1, value=0, key="js_mem")
        js_rev_input = st.number_input("매출", min_value=0, step=1, value=0, key="js_rev")

        if st.button("✅ 확인", key="btn_members", use_container_width=True):
            d_start = st.session_state.member_date_start
            d_end = st.session_state.member_date_end
            current = d_start
            while current <= d_end:
                st.session_state.member_data[str(current)] = {
                    "nv_cust": nv_cust_input,
                    "nv_rev": nv_rev_input,
                    "js_mem": js_mem_input,
                    "js_rev": js_rev_input,
                }
                save_member_day(str(current), nv_cust_input, nv_rev_input, js_mem_input, js_rev_input)
                current += timedelta(days=1)
            st.session_state.members_confirmed = True
            if d_start == d_end:
                st.success(f"{d_start} 데이터 입력 완료!")
            else:
                st.success(f"{d_start} ~ {d_end} 데이터 입력 완료!")

    elif mode_members == "파일 업로드":
        f1 = st.file_uploader("CSV / Excel", type=["csv", "xlsx", "xls"], key="f1")
        df_members_file = load_file(f1)
        if st.button("✅ 확인", key="btn_members_file", use_container_width=True):
            if df_members_file is not None:
                st.session_state.members_confirmed = True
                st.success("회원 현황 데이터 반영!")
            else:
                st.warning("파일을 먼저 업로드하세요.")
    else:
        if st.button("✅ 확인 (샘플)", key="btn_members_sample", use_container_width=True):
            st.session_state.members_confirmed = True
            st.success("샘플 데이터 반영!")

    st.divider()

    # ── 입력2: 광고 데이터 ──
    st.subheader("광고 데이터")

    # 데이터 구분
    ads_platform = st.radio(
        "데이터 구분",
        ["네이버", "META"],
        horizontal=True,
        key="ads_platform",
    )

    mode_ads = st.radio(
        "입력 방식",
        ["파일 업로드", "샘플"],
        horizontal=True,
        key="mode_ads",
    )
    df_ads_temp = None
    if mode_ads == "파일 업로드":
        f2 = st.file_uploader("CSV / Excel", type=["csv", "xlsx", "xls"], key="f2")
        df_ads_temp = load_file(f2)
    else:
        try:
            df_ads_temp = pd.read_csv("sample_data/naver_ads.csv")
        except FileNotFoundError:
            df_ads_temp = None

    if st.button("✅ 확인", key="btn_ads", use_container_width=True):
        if mode_ads == "샘플" or df_ads_temp is not None:
            st.session_state.ads_raw_data = df_ads_temp
            if df_ads_temp is not None:
                save_ads_data(df_ads_temp)
            # 상품 목록은 [+] 버튼으로만 수동 추가
            st.session_state.ads_confirmed = True
            st.success("광고 데이터 반영!")
        else:
            st.warning("데이터를 먼저 입력하세요.")


# ═════════════════════════════════════════════
# 회원 수 데이터 렌더링 함수
# ═════════════════════════════════════════════

def render_member_section(key_prefix):
    if not direct_input_mode:
        # 파일 업로드 / 샘플 모드
        if not st.session_state.members_confirmed:
            return

        if mode_members == "파일 업로드":
            df_mem = df_members_file
        else:
            try:
                df_mem = pd.read_csv("sample_data/members.csv")
            except FileNotFoundError:
                return

        if df_mem is None:
            return

        date_col_m = df_mem.columns[0]
        df_mem[date_col_m] = pd.to_datetime(df_mem[date_col_m], errors="coerce")
        member_col = [c for c in df_mem.columns if "회원수" in c][0]
        df_sorted = df_mem.sort_values(date_col_m).reset_index(drop=True)
        df_sorted["전일비 증감(명)"] = df_sorted[member_col].diff().fillna(0).astype(int)
        df_sorted["전일비 증감(%)"] = (df_sorted[member_col].pct_change().fillna(0) * 100).round(2)

        naver_col = [c for c in df_mem.columns if "네이버" in c][0]
        sales_col = [c for c in df_mem.columns if "매출" in c][0]

        _ms, _me = get_filter_date_range()
        st.subheader(f"회원 수 데이터 　{_ms.strftime('%y.%m.%d')} ~ {_me.strftime('%y.%m.%d')}")
        rows1 = []
        for _, r in df_sorted.iterrows():
            delta_cnt = int(r["전일비 증감(명)"])
            delta_pct = float(r["전일비 증감(%)"])
            rows1.append({
                "날짜": r[date_col_m].strftime("%Y-%m-%d") if pd.notna(r[date_col_m]) else "",
                "자사몰 회원수": fmt_number(r[member_col]),
                "전일비 증감(명)": ("+" if delta_cnt >= 0 else "") + fmt_number(delta_cnt),
                "전일비 증감(%)": ("+" if delta_pct >= 0 else "") + fmt_pct(delta_pct),
                "네이버 관심고객 증감율(%)": fmt_pct(r[naver_col]),
                "자사몰 당일 매출": fmt_money(r[sales_col]),
            })
        display1 = pd.DataFrame(rows1)
        styled1 = display1.style.map(color_delta, subset=["전일비 증감(명)", "전일비 증감(%)", "네이버 관심고객 증감율(%)"])
        st.dataframe(styled1, use_container_width=True, hide_index=True)
        return

    _ms2, _me2 = get_filter_date_range()
    st.subheader(f"회원 수 데이터 　{_ms2.strftime('%y.%m.%d')} ~ {_me2.strftime('%y.%m.%d')}")

    range_start, range_end = get_filter_date_range()
    dates = pd.date_range(start=range_start, end=range_end)
    n = len(dates)

    rows = []
    for d in dates:
        d_str = d.strftime("%Y-%m-%d")
        data = st.session_state.member_data.get(d_str, {})
        rows.append({
            "일자": d_str,
            "nv_cust": data.get("nv_cust", None),
            "nv_rev": data.get("nv_rev", None),
            "js_mem": data.get("js_mem", None),
            "js_rev": data.get("js_rev", None),
        })

    df = pd.DataFrame(rows)
    nv_cust = pd.to_numeric(df["nv_cust"], errors="coerce")
    nv_rev = pd.to_numeric(df["nv_rev"], errors="coerce")
    js_mem = pd.to_numeric(df["js_mem"], errors="coerce")
    js_rev = pd.to_numeric(df["js_rev"], errors="coerce")

    nv_increase = nv_cust.diff()
    js_increase = js_mem.diff()
    nv_growth = nv_cust.pct_change().mul(100).round(2)
    js_growth = js_mem.pct_change().mul(100).round(2)

    nv_mean = nv_cust.mean()
    js_mean = js_mem.mean()
    nv_avg_diff = ((nv_cust - nv_mean) / nv_mean * 100).round(2) if pd.notna(nv_mean) and nv_mean != 0 else pd.Series([None] * n)
    js_avg_diff = ((js_mem - js_mean) / js_mean * 100).round(2) if pd.notna(js_mean) and js_mean != 0 else pd.Series([None] * n)

    def safe_fmt_num(x):
        return fmt_number(x) if pd.notna(x) and x != 0 else ""
    def safe_fmt_money(x):
        return fmt_money(x) if pd.notna(x) and x != 0 else ""
    def safe_fmt_delta(x):
        return f"{x:+.2f}%" if pd.notna(x) else ""
    def safe_fmt_increase(x):
        if pd.notna(x):
            v = int(x)
            return f"+{v:,}" if v >= 0 else f"{v:,}"
        return ""

    result = pd.DataFrame({
        ("회원 수 데이터", "일자"): df["일자"],
        ("네이버", "관심 고객수"): nv_cust.apply(safe_fmt_num),
        ("네이버", "매출"): nv_rev.apply(safe_fmt_money),
        ("네이버", "회원 증가수"): nv_increase.apply(safe_fmt_increase),
        ("네이버", "회원 증감율"): nv_growth.apply(safe_fmt_delta),
        ("네이버", "평균대비"): nv_avg_diff.apply(safe_fmt_delta),
        ("자사몰", "회원수"): js_mem.apply(safe_fmt_num),
        ("자사몰", "매출"): js_rev.apply(safe_fmt_money),
        ("자사몰", "회원 증가수"): js_increase.apply(safe_fmt_increase),
        ("자사몰", "회원 증감율"): js_growth.apply(safe_fmt_delta),
        ("자사몰", "평균대비"): js_avg_diff.apply(safe_fmt_delta),
    })
    result.columns = pd.MultiIndex.from_tuples(result.columns)

    delta_cols = [
        ("네이버", "회원 증가수"), ("네이버", "회원 증감율"), ("네이버", "평균대비"),
        ("자사몰", "회원 증가수"), ("자사몰", "회원 증감율"), ("자사몰", "평균대비"),
    ]
    styled = result.style.map(color_delta, subset=delta_cols)
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════
# 광고 데이터 렌더링 함수
# ═════════════════════════════════════════════

def render_ads_section(key_prefix):
    _ads_s, _ads_e = get_filter_date_range()
    st.subheader(f"광고 데이터 분석 　{_ads_s.strftime('%y.%m.%d')} ~ {_ads_e.strftime('%y.%m.%d')}")

    if not st.session_state.ads_confirmed:
        return

    df_ads = st.session_state.ads_raw_data
    if df_ads is None:
        return

    df_ads = df_ads.copy()

    # ── 컬럼 자동 감지 ──
    date_col = find_col(df_ads, "일") or find_col(df_ads, "날짜") or find_col(df_ads, "기간")
    if date_col is None:
        date_col = df_ads.columns[0]

    cost_col = find_col(df_ads, "총비용") or find_col(df_ads, "총 비용")
    purchase_col = find_col(df_ads, "구매완료수") or find_col(df_ads, "구매전환수")
    purchase_rev_col = find_col(df_ads, "구매완료 전환 매출") or find_col(df_ads, "구매완료", "매출") or find_col(df_ads, "총구매전환매출")
    prod_col = find_col(df_ads, "광고 그룹", exclude=["ID", "Id"]) or find_col(df_ads, "광고그룹", exclude=["ID", "Id"]) or find_col(df_ads, "상품명")
    campaign_col = find_col(df_ads, "캠페인", exclude=["ID", "Id"])

    # 날짜 정규화
    df_ads[date_col] = pd.to_datetime(
        df_ads[date_col].astype(str).str.replace(".", "-", regex=False),
        errors="coerce"
    )

    # ── 날짜 범위 필터링 (공용 필터 사용) ──
    range_start, range_end = get_filter_date_range()
    df_ads = df_ads[
        (df_ads[date_col] >= range_start) & (df_ads[date_col] <= range_end)
    ]

    if df_ads.empty:
        st.warning(f"선택한 날짜 범위({range_start.strftime('%Y-%m-%d')} ~ {range_end.strftime('%Y-%m-%d')})에 해당하는 데이터가 없습니다.")
        return

    # ── 3-1. 상품 버튼 시스템 ──
    product_list = st.session_state.product_list

    # 상품 버튼 표시
    if product_list:
        btn_cols = st.columns(min(len(product_list) + 2, 10))
        col_idx = 0

        # 전체 버튼
        with btn_cols[col_idx % len(btn_cols)]:
            if st.button("전체", key=f"{key_prefix}_prod_all", use_container_width=True,
                         type="primary" if st.session_state.selected_product is None else "secondary"):
                st.session_state.selected_product = None
                st.rerun()
        col_idx += 1

        # 각 상품 버튼
        products_to_remove = []
        for p in product_list:
            with btn_cols[col_idx % len(btn_cols)]:
                bc1, bc2 = st.columns([4, 1])
                with bc1:
                    if st.button(p, key=f"{key_prefix}_prod_{p}", use_container_width=True,
                                 type="primary" if st.session_state.selected_product == p else "secondary"):
                        st.session_state.selected_product = p
                        st.rerun()
                with bc2:
                    if st.button("X", key=f"{key_prefix}_del_{p}"):
                        products_to_remove.append(p)
            col_idx += 1

        # 삭제 처리
        if products_to_remove:
            for p in products_to_remove:
                if p in st.session_state.product_list:
                    st.session_state.product_list.remove(p)
            save_products(st.session_state.product_list)
            if st.session_state.selected_product in products_to_remove:
                st.session_state.selected_product = None
            st.rerun()

    # [+] 추가 버튼
    add_col1, add_col2 = st.columns([1, 5])
    with add_col1:
        if st.button("+", key=f"{key_prefix}_add_prod"):
            st.session_state.adding_product = not st.session_state.adding_product
            st.rerun()

    if st.session_state.adding_product:
        with add_col2:
            new_name = st.text_input("상품명 입력", key=f"{key_prefix}_new_prod_name")
            if st.button("추가", key=f"{key_prefix}_confirm_add"):
                if new_name.strip() and new_name.strip() not in st.session_state.product_list:
                    st.session_state.product_list.append(new_name.strip())
                    save_products(st.session_state.product_list)
                    st.session_state.adding_product = False
                    st.rerun()

    # ── 상품 필터링 ──
    selected = st.session_state.selected_product
    if selected and prod_col and prod_col in df_ads.columns:
        mask = df_ads[prod_col].astype(str).str.contains(selected, case=False, na=False, regex=False)
        df_filtered = df_ads[mask]
    else:
        df_filtered = df_ads

    # ── 3-3. 네이버스토어/자사몰/META 서브탭 ──
    sub_all, sub_naver, sub_jasamol, sub_meta = st.tabs(["전체", "네이버스토어", "자사몰", "META"])

    def render_ads_table(df_sub, tab_key):
        if df_sub.empty:
            st.info("해당 조건의 데이터가 없습니다.")
            return

        # 숫자 변환
        numeric_cols = []
        for col in df_sub.columns:
            if col == date_col or col == prod_col or col == campaign_col:
                continue
            df_sub[col] = pd.to_numeric(df_sub[col].astype(str).str.replace(",", ""), errors="coerce")
            numeric_cols.append(col)

        # 날짜순 정렬
        df_sub = df_sub.sort_values(date_col)

        # 계산 컬럼 추가
        if cost_col and purchase_col:
            df_sub["CPA"] = df_sub.apply(lambda r: safe_divide(r.get(cost_col, 0), r.get(purchase_col, 0)), axis=1)
        if purchase_rev_col and purchase_col:
            df_sub["AOV"] = df_sub.apply(lambda r: safe_divide(r.get(purchase_rev_col, 0), r.get(purchase_col, 0)), axis=1)
        if purchase_rev_col and cost_col:
            df_sub["ROAS"] = df_sub.apply(lambda r: safe_divide(r.get(purchase_rev_col, 0), r.get(cost_col, 0)) * 100, axis=1)

        # 표시할 컬럼 구성 (일자를 첫 열로)
        display_cols = [date_col]
        for c in df_sub.columns:
            if c == date_col:
                continue
            if c == prod_col or c == campaign_col:
                continue
            if "ID" in str(c) or "Id" in str(c):
                continue
            if c in ["결과 유형", "결과당 비용 유형", "결과유형", "결과당 비용유형"]:
                continue
            display_cols.append(c)

        df_display = df_sub[display_cols].copy()

        # 컬럼명 정리: 첫 열을 "일자"로 표시
        rename_map = {date_col: "일자"}
        df_display = df_display.rename(columns=rename_map)

        # ── 합계행 계산 (포맷팅 전, 숫자 상태에서) ──
        # 평균 컬럼: CPC, CPA, AOV, ROAS, CTR 등 비율/단가 지표
        # 합계 컬럼: 결과, 총비용, 구매완료수, 매출, 장바구니 등 절대값 지표
        avg_keywords = ["CPC", "CPM", "CPA", "AOV", "ROAS", "CTR", "율", "결과당"]
        summary = {"일자": "합계"}
        for c in df_display.columns:
            if c == "일자":
                continue
            vals = pd.to_numeric(df_display[c], errors="coerce")
            if any(k in c for k in avg_keywords):
                summary[c] = vals.mean()
            else:
                summary[c] = vals.sum()

        # 날짜 포맷팅
        df_display["일자"] = df_display["일자"].apply(
            lambda x: x.strftime("%Y-%m-%d") if hasattr(x, "strftime") else str(x) if pd.notna(x) else ""
        )

        # 숫자 포맷팅 함수
        def format_col(c, x):
            if pd.isna(x):
                return ""
            if c in ["CPA", "AOV"]:
                return fmt_money(x)
            elif c == "ROAS":
                return fmt_pct(x, 1)
            elif "비용" in c or "매출" in c or "CPC" in c or "CPM" in c or "결과당" in c:
                return fmt_money(x)
            elif "CTR" in c or "율" in c:
                return fmt_pct(x)
            else:
                return fmt_number(x)

        # 합계행 포맷팅
        summary_formatted = {"일자": "합계"}
        for c in df_display.columns:
            if c == "일자":
                continue
            summary_formatted[c] = format_col(c, summary[c])

        # 데이터 행 포맷팅
        for c in df_display.columns:
            if c == "일자":
                continue
            df_display[c] = df_display[c].apply(lambda x: format_col(c, x))

        # 합계행 추가
        summary_row = pd.DataFrame([summary_formatted])
        df_display = pd.concat([df_display, summary_row], ignore_index=True)

        # 합계행 분리
        df_data = df_display.iloc[:-1]
        summary_vals = df_display.iloc[-1]

        # 합계 카드 표시 (테이블 위에 고정)
        sum_cols = [c for c in df_display.columns if c != "일자"]
        with st.container():
            st.markdown(
                "<div style='padding:8px 12px; background:rgba(231,76,60,0.1); border-left:3px solid #e74c3c; border-radius:4px; margin-bottom:4px;'>"
                + " &nbsp;|&nbsp; ".join([f"<b>{c}</b> {summary_vals[c]}" for c in sum_cols])
                + "</div>",
                unsafe_allow_html=True,
            )

        st.dataframe(df_data, use_container_width=True, hide_index=True)

    with sub_all:
        render_ads_table(df_filtered.copy(), f"{key_prefix}_all")

    with sub_naver:
        if campaign_col:
            df_naver = df_filtered[df_filtered[campaign_col].astype(str).str.contains("네이버", na=False)].copy()
        else:
            df_naver = df_filtered.copy()
        render_ads_table(df_naver, f"{key_prefix}_naver")

    with sub_jasamol:
        if campaign_col:
            df_jasamol = df_filtered[df_filtered[campaign_col].astype(str).str.contains("자사몰", na=False)].copy()
        else:
            df_jasamol = df_filtered.copy()
        render_ads_table(df_jasamol, f"{key_prefix}_jasamol")

    with sub_meta:
        st.info("META 광고 데이터 분석 준비 중입니다.")


# ─────────────────────────────────────────────
# 공용 날짜 필터 (탭 위)
# ─────────────────────────────────────────────

def cb_filter_all():
    st.session_state.filter_mode = "전체"
    st.session_state.filter_year = today.year
    st.session_state.filter_month = today.month
    st.session_state.filter_week = 1

def cb_year_left():
    st.session_state.filter_year -= 1
    st.session_state.filter_mode = "기간"

def cb_year_right():
    st.session_state.filter_year += 1
    st.session_state.filter_mode = "기간"

def cb_year_label():
    st.session_state.filter_mode = "기간"

def cb_month_left():
    st.session_state.filter_month -= 1
    if st.session_state.filter_month < 1:
        st.session_state.filter_month = 12
        st.session_state.filter_year -= 1
    st.session_state.filter_mode = "기간"

def cb_month_right():
    st.session_state.filter_month += 1
    if st.session_state.filter_month > 12:
        st.session_state.filter_month = 1
        st.session_state.filter_year += 1
    st.session_state.filter_mode = "기간"

def cb_month_label():
    st.session_state.filter_mode = "기간"

def cb_week_left():
    st.session_state.filter_week -= 1
    if st.session_state.filter_week < 1:
        st.session_state.filter_month -= 1
        if st.session_state.filter_month < 1:
            st.session_state.filter_month = 12
            st.session_state.filter_year -= 1
        st.session_state.filter_week = get_max_weeks(st.session_state.filter_year, st.session_state.filter_month)
    st.session_state.filter_mode = "기간"

def cb_week_right():
    max_w = get_max_weeks(st.session_state.filter_year, st.session_state.filter_month)
    st.session_state.filter_week += 1
    if st.session_state.filter_week > max_w:
        st.session_state.filter_week = 1
        st.session_state.filter_month += 1
        if st.session_state.filter_month > 12:
            st.session_state.filter_month = 1
            st.session_state.filter_year += 1
    st.session_state.filter_mode = "기간"

def cb_week_label():
    st.session_state.filter_mode = "기간"


def get_filter_date_range():
    """공용 날짜 범위 계산"""
    f_mode = st.session_state.filter_mode
    if f_mode == "전체":
        if st.session_state.member_data:
            all_dates = sorted(st.session_state.member_data.keys())
            return pd.Timestamp(all_dates[0]), pd.Timestamp(all_dates[-1])
        else:
            return pd.Timestamp(today - timedelta(days=9)), pd.Timestamp(today)
    else:
        w_start, w_end = get_week_range(st.session_state.filter_year, st.session_state.filter_month, st.session_state.filter_week)
        return pd.Timestamp(w_start), pd.Timestamp(w_end)


# 필터 버튼 UI
c_all, c_year, c_month, c_week = st.columns(4)

with c_all:
    st.button("전체", key="global_filter_all", use_container_width=True, on_click=cb_filter_all)

with c_year:
    yl, ylabel, yr = st.columns([1, 3, 1])
    with yl:
        st.button("◀", key="global_year_left", use_container_width=True, on_click=cb_year_left)
    with ylabel:
        st.button(f"{st.session_state.filter_year}년", key="global_year_label", use_container_width=True, on_click=cb_year_label)
    with yr:
        st.button("▶", key="global_year_right", use_container_width=True, on_click=cb_year_right)

with c_month:
    ml, mlabel, mr = st.columns([1, 3, 1])
    with ml:
        st.button("◀", key="global_month_left", use_container_width=True, on_click=cb_month_left)
    with mlabel:
        st.button(f"{st.session_state.filter_month}월", key="global_month_label", use_container_width=True, on_click=cb_month_label)
    with mr:
        st.button("▶", key="global_month_right", use_container_width=True, on_click=cb_month_right)

with c_week:
    wl, wlabel, wr = st.columns([1, 3, 1])
    with wl:
        st.button("◀", key="global_week_left", use_container_width=True, on_click=cb_week_left)
    with wlabel:
        st.button(f"{st.session_state.filter_week}주차", key="global_week_label", use_container_width=True, on_click=cb_week_label)
    with wr:
        st.button("▶", key="global_week_right", use_container_width=True, on_click=cb_week_right)


# ═════════════════════════════════════════════
# 광고 데이터 분석 렌더링 함수
# ═════════════════════════════════════════════

def render_analysis_section(key_prefix):
    _an_start, _an_end = get_filter_date_range()
    st.subheader(f"광고 데이터 분석 　{_an_start.strftime('%y.%m.%d')} ~ {_an_end.strftime('%y.%m.%d')}")

    df_raw = st.session_state.ads_raw_data
    if df_raw is None or not st.session_state.ads_confirmed:
        st.info("광고 데이터를 먼저 업로드하세요.")
        return

    df_an = df_raw.copy()

    # 컬럼 감지
    an_date_col = find_col(df_an, "일") or find_col(df_an, "날짜") or find_col(df_an, "기간") or df_an.columns[0]
    an_cost_col = find_col(df_an, "총비용") or find_col(df_an, "총 비용")
    an_purchase_col = find_col(df_an, "구매완료수") or find_col(df_an, "구매전환수")
    an_rev_col = find_col(df_an, "구매완료 전환 매출") or find_col(df_an, "구매완료", "매출") or find_col(df_an, "총구매전환매출")
    an_prod_col = find_col(df_an, "광고 그룹", exclude=["ID", "Id"]) or find_col(df_an, "광고그룹", exclude=["ID", "Id"]) or find_col(df_an, "상품명")

    # 날짜 정규화
    df_an[an_date_col] = pd.to_datetime(df_an[an_date_col].astype(str).str.replace(".", "-", regex=False), errors="coerce")

    # 날짜 필터 적용
    an_range_start, an_range_end = get_filter_date_range()
    df_an = df_an[(df_an[an_date_col] >= an_range_start) & (df_an[an_date_col] <= an_range_end)]

    if df_an.empty:
        st.warning("선택한 기간에 데이터가 없습니다.")
        return

    # 숫자 변환
    for col in [an_cost_col, an_purchase_col, an_rev_col]:
        if col:
            df_an[col] = pd.to_numeric(df_an[col].astype(str).str.replace(",", ""), errors="coerce").fillna(0)

    # ── 1. 전일비 요약 카드 ──
    st.markdown("### 전일비 요약")

    product_list_an = st.session_state.product_list

    def calc_daily_metrics(df_subset):
        daily = df_subset.groupby(an_date_col).agg(
            총비용=(an_cost_col, "sum") if an_cost_col else (df_subset.columns[0], "count"),
            구매수=(an_purchase_col, "sum") if an_purchase_col else (df_subset.columns[0], "count"),
            매출=(an_rev_col, "sum") if an_rev_col else (df_subset.columns[0], "count"),
        ).sort_index()

        if len(daily) < 1:
            return None

        daily["CPA"] = daily.apply(lambda r: safe_divide(r["총비용"], r["구매수"]), axis=1)
        daily["ROAS"] = daily.apply(lambda r: safe_divide(r["매출"], r["총비용"]) * 100, axis=1)
        return daily

    if an_cost_col and an_purchase_col and an_rev_col:
        daily_all = calc_daily_metrics(df_an)

        if daily_all is not None and len(daily_all) >= 1:
            last = daily_all.iloc[-1]
            last_date = daily_all.index[-1]
            prev = daily_all.iloc[-2] if len(daily_all) >= 2 else None
            prev_date = daily_all.index[-2] if len(daily_all) >= 2 else None

            if prev_date is not None:
                st.caption(f"기준: {last_date.strftime('%m/%d')} vs 전일 {prev_date.strftime('%m/%d')}")
            else:
                st.caption(f"기준: {last_date.strftime('%m/%d')} (전일 데이터 없음)")

            card_cols = st.columns(5)
            metrics = [
                ("총 광고비", last["총비용"], prev["총비용"] if prev is not None else None, "₩"),
                ("총 매출", last["매출"], prev["매출"] if prev is not None else None, "₩"),
                ("구매수", last["구매수"], prev["구매수"] if prev is not None else None, ""),
                ("CPA", last["CPA"], prev["CPA"] if prev is not None else None, "₩"),
                ("ROAS", last["ROAS"], prev["ROAS"] if prev is not None else None, "%"),
            ]

            for i, (label, val, prev_val, unit) in enumerate(metrics):
                with card_cols[i]:
                    if unit == "₩":
                        display_val = fmt_money(val)
                    elif unit == "%":
                        display_val = fmt_pct(val, 1)
                    else:
                        display_val = fmt_number(val)

                    if prev_val is not None and prev_val != 0:
                        delta_pct = (val - prev_val) / prev_val * 100
                        delta_str = f"{delta_pct:+.1f}%"
                        if label == "CPA":
                            delta_color = "inverse"
                        else:
                            delta_color = "normal"
                        st.metric(label, display_val, delta_str, delta_color=delta_color)
                    else:
                        st.metric(label, display_val)

        st.divider()

        # ── 2. 상품별 ROAS 비교 막대 그래프 ──
        st.markdown("### 상품별 ROAS 비교")

        if an_prod_col and product_list_an:
            roas_data = []
            for prod in product_list_an:
                mask = df_an[an_prod_col].astype(str).str.contains(prod, case=False, na=False, regex=False)
                df_prod = df_an[mask]
                if df_prod.empty:
                    continue
                total_cost = df_prod[an_cost_col].sum()
                total_rev = df_prod[an_rev_col].sum()
                total_purchases = df_prod[an_purchase_col].sum()
                roas_val = safe_divide(total_rev, total_cost) * 100
                cpa_val = safe_divide(total_cost, total_purchases)
                roas_data.append({
                    "상품명": prod,
                    "ROAS": round(roas_val, 1),
                    "CPA": round(cpa_val),
                    "총비용": total_cost,
                    "매출": total_rev,
                })

            if roas_data:
                df_roas = pd.DataFrame(roas_data).sort_values("ROAS", ascending=True)

                fig_roas = px.bar(
                    df_roas, x="ROAS", y="상품명", orientation="h",
                    text="ROAS",
                    color="ROAS",
                    color_continuous_scale=["#dc2626", "#f59e0b", "#16a34a"],
                )
                fig_roas.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                fig_roas.update_layout(
                    height=max(300, len(df_roas) * 50),
                    margin=dict(l=0, r=50, t=10, b=0),
                    coloraxis_showscale=False,
                    xaxis_title="ROAS (%)",
                    yaxis_title="",
                )
                st.plotly_chart(fig_roas, use_container_width=True, key=f"{key_prefix}_roas_chart")
            else:
                st.info("상품별 데이터가 없습니다.")
        else:
            st.info("상품 목록을 추가하면 상품별 비교가 표시됩니다.")

        st.divider()

        # ── 3. 일별 CPA 추이 꺾은선 그래프 ──
        st.markdown("### 일별 CPA / ROAS 추이")

        if daily_all is not None and len(daily_all) >= 2:
            df_trend = daily_all.reset_index()
            df_trend["날짜"] = df_trend[an_date_col].dt.strftime("%m/%d")

            fig_trend = go.Figure()
            fig_trend.add_trace(go.Scatter(
                x=df_trend["날짜"], y=df_trend["CPA"],
                name="CPA", mode="lines+markers",
                line=dict(color="#dc2626", width=2),
                yaxis="y",
            ))
            fig_trend.add_trace(go.Scatter(
                x=df_trend["날짜"], y=df_trend["ROAS"],
                name="ROAS", mode="lines+markers",
                line=dict(color="#16a34a", width=2),
                yaxis="y2",
            ))
            fig_trend.update_layout(
                height=400,
                margin=dict(l=0, r=0, t=30, b=0),
                yaxis=dict(title="CPA (₩)", side="left", showgrid=False),
                yaxis2=dict(title="ROAS (%)", side="right", overlaying="y", showgrid=False),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                hovermode="x unified",
            )
            st.plotly_chart(fig_trend, use_container_width=True, key=f"{key_prefix}_trend_chart")

            # 상품별 CPA 추이
            if an_prod_col and product_list_an:
                st.markdown("### 상품별 CPA 추이")
                trend_data = []
                for prod in product_list_an:
                    mask = df_an[an_prod_col].astype(str).str.contains(prod, case=False, na=False, regex=False)
                    df_p = df_an[mask]
                    if df_p.empty:
                        continue
                    daily_p = df_p.groupby(an_date_col).agg(
                        총비용=(an_cost_col, "sum"),
                        구매수=(an_purchase_col, "sum"),
                    ).sort_index().reset_index()
                    daily_p["CPA"] = daily_p.apply(lambda r: safe_divide(r["총비용"], r["구매수"]), axis=1)
                    daily_p["상품명"] = prod
                    daily_p["날짜"] = daily_p[an_date_col]
                    trend_data.append(daily_p[["날짜", "CPA", "상품명"]])

                if trend_data:
                    df_all_trend = pd.concat(trend_data)
                    fig_cpa = px.line(
                        df_all_trend, x="날짜", y="CPA", color="상품명",
                        markers=True,
                    )
                    fig_cpa.update_layout(
                        height=400,
                        margin=dict(l=0, r=0, t=10, b=0),
                        yaxis_title="CPA (₩)",
                        xaxis_title="",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        hovermode="x unified",
                    )
                    st.plotly_chart(fig_cpa, use_container_width=True, key=f"{key_prefix}_cpa_chart")
        else:
            st.info("추이 분석을 위해 2일 이상의 데이터가 필요합니다.")
    else:
        st.warning("총비용, 구매완료수, 매출 컬럼을 찾을 수 없습니다.")


# ─────────────────────────────────────────────
# 상단 탭 네비게이션 + 콘텐츠
# ─────────────────────────────────────────────

tab_all, tab_members, tab_ads, tab_analysis = st.tabs(["전체", "회원현황", "광고 데이터", "광고 데이터 분석"])

with tab_all:
    render_member_section("all_m")
    st.divider()
    render_ads_section("all_a")
    st.divider()
    render_analysis_section("all_an")

with tab_members:
    render_member_section("mem")

with tab_ads:
    render_ads_section("ads")

with tab_analysis:
    render_analysis_section("analysis")
