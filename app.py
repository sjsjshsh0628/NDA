import streamlit as st
import pandas as pd
import io
from typing import Optional

st.set_page_config(
    page_title="일간 마케팅 대시보드",
    page_icon="📊",
    layout="wide",
)

st.title("📊 일간 마케팅 대시보드")

# ─────────────────────────────────────────────
# 헬퍼 함수
# ─────────────────────────────────────────────

def parse_paste(text: str) -> Optional[pd.DataFrame]:
    """탭/쉼표 구분 텍스트를 DataFrame으로 변환"""
    text = text.strip()
    if not text:
        return None
    sep = "\t" if "\t" in text else ","
    try:
        return pd.read_csv(io.StringIO(text), sep=sep)
    except Exception as e:
        st.error(f"붙여넣기 파싱 오류: {e}")
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
    """양수=초록, 음수=빨강"""
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


# ─────────────────────────────────────────────
# 사이드바 — 데이터 입력
# ─────────────────────────────────────────────

with st.sidebar:
    st.header("📥 데이터 입력")

    df_members: Optional[pd.DataFrame] = None
    df_ads: Optional[pd.DataFrame] = None

    # ── 입력1: 회원 현황 ──
    st.subheader("입력1 — 자사몰·네이버 회원 현황")
    mode_members = st.radio(
        "입력 방식",
        ["직접 붙여넣기", "파일 업로드", "샘플"],
        horizontal=True,
        key="mode_members",
    )
    if mode_members == "직접 붙여넣기":
        st.caption("Excel에서 범위 복사(Ctrl+C) 후 아래에 붙여넣기(Ctrl+V)")
        MEMBERS_PLACEHOLDER = (
            "날짜\t자사몰 회원수\t네이버 관심고객 증감율(%)\t자사몰 당일 매출\n"
            "2026-03-14\t12810\t2.1\t6450000\n"
            "2026-03-15\t12905\t1.8\t7120000"
        )
        txt1 = st.text_area(
            "회원 현황 붙여넣기",
            height=160,
            key="txt1",
            placeholder=MEMBERS_PLACEHOLDER,
        )
        df_members = parse_paste(txt1) if txt1.strip() else None
    elif mode_members == "파일 업로드":
        f1 = st.file_uploader("CSV / Excel", type=["csv", "xlsx", "xls"], key="f1")
        df_members = load_file(f1)
    else:
        try:
            df_members = pd.read_csv("sample_data/members.csv")
            st.caption("샘플 데이터 사용 중")
        except FileNotFoundError:
            st.error("sample_data/members.csv 없음")

    st.divider()

    # ── 입력2: 네이버 광고 ──
    st.subheader("입력2 — 네이버 광고 로우데이터")
    mode_ads = st.radio(
        "입력 방식",
        ["파일 업로드", "직접 붙여넣기", "샘플"],
        horizontal=True,
        key="mode_ads",
    )
    if mode_ads == "파일 업로드":
        f2 = st.file_uploader("CSV / Excel", type=["csv", "xlsx", "xls"], key="f2")
        df_ads = load_file(f2)
    elif mode_ads == "직접 붙여넣기":
        st.caption("헤더 포함, 탭 또는 쉼표 구분")
        txt2 = st.text_area("광고 데이터 붙여넣기", height=200, key="txt2")
        df_ads = parse_paste(txt2) if txt2.strip() else None
    else:
        try:
            df_ads = pd.read_csv("sample_data/naver_ads.csv")
            st.caption("샘플 데이터 사용 중")
        except FileNotFoundError:
            st.error("sample_data/naver_ads.csv 없음")

# ─────────────────────────────────────────────
# 데이터 전처리
# ─────────────────────────────────────────────

if df_members is None or df_ads is None:
    st.info("사이드바에서 데이터를 입력해 주세요.")
    st.stop()

# 날짜 컬럼 정규화
date_col_m = df_members.columns[0]
date_col_candidates = [c for c in df_ads.columns if "기간" in str(c)]
date_col_a = date_col_candidates[0] if date_col_candidates else df_ads.columns[0]
df_members[date_col_m] = pd.to_datetime(df_members[date_col_m], errors="coerce")
df_ads[date_col_a] = pd.to_datetime(
    df_ads[date_col_a].astype(str).str.replace(".", "-", regex=False),
    errors="coerce"
)

# 컬럼 탐지
revenue_col = [c for c in df_ads.columns if "전환 매출" in str(c) or ("매출" in str(c) and "구매완료" not in str(c))]
cost_col = [c for c in df_ads.columns if "총 비용" in str(c) or ("총비용" in str(c) and "전환" not in str(c))]
campaign_col_candidates = [c for c in df_ads.columns if "캠페인 이름" in str(c)]
campaign_col = campaign_col_candidates[0] if campaign_col_candidates else None

# ROAS — CSV에 있으면 사용, 없으면 계산
roas_col_candidates = [c for c in df_ads.columns if "수익률" in str(c) or "ROAS" in str(c)]
if roas_col_candidates:
    df_ads["ROAS"] = pd.to_numeric(df_ads[roas_col_candidates[0]], errors="coerce").round(1)
elif revenue_col and cost_col:
    df_ads["ROAS"] = (
        pd.to_numeric(df_ads[revenue_col[0]], errors="coerce")
        / pd.to_numeric(df_ads[cost_col[0]], errors="coerce")
        * 100
    ).round(1)

# 전일 대비 자동 계산
member_col = [c for c in df_members.columns if "회원수" in c][0]
df_members_sorted = df_members.sort_values(date_col_m).reset_index(drop=True)
df_members_sorted["전일비 증감(명)"] = df_members_sorted[member_col].diff().fillna(0).astype(int)
df_members_sorted["전일비 증감(%)"] = (
    df_members_sorted[member_col].pct_change().fillna(0) * 100
).round(2)

# ─────────────────────────────────────────────
# 필터 — 상품
# ─────────────────────────────────────────────

# 상품 목록 추출
prod_col_candidates = [c for c in df_ads.columns if ("광고 그룹" in str(c) and "ID" not in str(c)) or "상품명" in str(c)]
prod_col = prod_col_candidates[0] if prod_col_candidates else df_ads.columns[0]
products_sorted = sorted(df_ads[prod_col].dropna().unique().tolist())

sort_mode = st.radio("상품 정렬", ["가나다순", "직접 지정"], horizontal=True)
if sort_mode == "직접 지정":
    order_input = st.text_input("원하는 순서로 상품명 입력 (쉼표 구분)", value=", ".join(products_sorted))
    custom_order = [p.strip() for p in order_input.split(",") if p.strip()]
    product_list = custom_order + [p for p in products_sorted if p not in custom_order]
else:
    product_list = products_sorted

selected_product = st.selectbox("상품 선택", product_list)

st.divider()

# ─────────────────────────────────────────────
# 표 1 — 자사몰·네이버 회원 현황
# ─────────────────────────────────────────────

st.subheader("자사몰·네이버 회원 현황")

naver_col = [c for c in df_members.columns if "네이버" in c][0]
sales_col = [c for c in df_members.columns if "매출" in c][0]

rows1 = []
for _, r in df_members_sorted.iterrows():
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

st.divider()

# ─────────────────────────────────────────────
# 표 2 — 자사몰 캠페인 (선택 상품)
# ─────────────────────────────────────────────

st.subheader(f"자사몰 캠페인 — {selected_product}")

# 구매전환수: "결과" 키워드 (단, "유형"·"당" 제외)
conv_col = [c for c in df_ads.columns if "결과" in str(c) and "유형" not in str(c) and "당" not in str(c)]
# 전환당단가: "결과당 비용" (단, "유형" 제외)
cpa_col = [c for c in df_ads.columns if "결과당 비용" in str(c) and "유형" not in str(c)]
# 총전환비용: "총 비용" 또는 "총비용"
conv_cost_col = [c for c in df_ads.columns if "총 비용" in str(c) or ("총비용" in str(c) and "전환" not in str(c))]

if campaign_col is not None:
    mask_a2 = (df_ads[prod_col] == selected_product) & df_ads[campaign_col].str.contains("자사몰", na=False)
else:
    mask_a2 = df_ads[prod_col] == selected_product
df_a2 = df_ads[mask_a2].sort_values(date_col_a)

rows2 = []
for _, r2 in df_a2.iterrows():
    roas_val = r2.get("ROAS", None)
    rows2.append({
        "날짜": r2[date_col_a].strftime("%Y-%m-%d") if pd.notna(r2[date_col_a]) else "",
        "구매전환수": fmt_number(r2[conv_col[0]]) if conv_col else "N/A",
        "전환당단가": fmt_money(r2[cpa_col[0]]) if cpa_col else "N/A",
        "총전환비용": fmt_money(r2[conv_cost_col[0]]) if conv_cost_col else "N/A",
        "ROAS": fmt_pct(roas_val, 1) if pd.notna(roas_val) else "N/A",
    })

if rows2:
    st.dataframe(pd.DataFrame(rows2), use_container_width=True, hide_index=True)
else:
    st.warning(f"{selected_product} 자사몰 데이터가 없습니다.")

st.divider()

# ─────────────────────────────────────────────
# 표 3 — 네이버스토어 (선택 상품)
# ─────────────────────────────────────────────

st.subheader(f"네이버스토어 — {selected_product}")

cpc_col = [c for c in df_ads.columns if "CPC" in str(c)]
ctr_col = [c for c in df_ads.columns if "전환율" in str(c)]
rev_col = [c for c in df_ads.columns if "전환 매출" in str(c) or ("매출" in str(c) and "구매완료" not in str(c))]

if campaign_col is not None:
    mask_a3 = (df_ads[prod_col] == selected_product) & df_ads[campaign_col].str.contains("네이버", na=False)
else:
    mask_a3 = df_ads[prod_col] == selected_product
df_a3 = df_ads[mask_a3].sort_values(date_col_a)

rows3 = []
for _, r3 in df_a3.iterrows():
    roas_val3 = r3.get("ROAS", None)
    rows3.append({
        "날짜": r3[date_col_a].strftime("%Y-%m-%d") if pd.notna(r3[date_col_a]) else "",
        "CPC": fmt_money(r3[cpc_col[0]]) if cpc_col else "N/A",
        "CTR(%)": fmt_pct(r3[ctr_col[0]]) if ctr_col else "N/A",
        "총비용": fmt_money(r3[cost_col[0]]) if cost_col else "N/A",
        "총구매전환매출": fmt_money(r3[rev_col[0]]) if rev_col else "N/A",
        "ROAS": fmt_pct(roas_val3, 1) if pd.notna(roas_val3) else "N/A",
    })

if rows3:
    st.dataframe(pd.DataFrame(rows3), use_container_width=True, hide_index=True)
else:
    st.warning(f"{selected_product} 네이버스토어 데이터가 없습니다.")
