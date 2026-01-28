from datetime import datetime, date, timedelta

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from supabase import create_client

# -----------------------
# Config / Constants
# -----------------------
EMOTIONS = ["嬉しい", "安心", "怒り", "不安", "悲しい", "疲れ", "焦り", "ワクワク", "無感情", "その他"]

st.set_page_config(page_title="思考が見える日記", page_icon="🧠", layout="wide")

# ---- UI: max width / spacing ----
st.markdown("""
<style>
/* 画面中央に読みやすい幅で集約 */
.block-container {max-width: 1200px; margin: auto; padding-top: 2.0rem; padding-bottom: 2.0rem;}
/* 見出しの詰まりを少し改善 */
h1, h2, h3 {letter-spacing: -0.02em;}
/* カード風（フォーム・右上サマリ） */
.card {
  background: rgba(255,255,255,0.85);
  border: 1px solid rgba(229,231,235,0.9);
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 8px 24px rgba(17,24,39,0.06);
}
.small {color: #6b7280; font-size: 0.9rem;}
</style>
""", unsafe_allow_html=True)


# -----------------------
# Supabase
# -----------------------
@st.cache_resource
def get_supabase():
    cfg = st.secrets["connections"]["supabase"]
    supabase_url = cfg["SUPABASE_URL"]
    supabase_key = cfg["SUPABASE_KEY"]
    return create_client(supabase_url, supabase_key)

supabase = get_supabase()


# -----------------------
# DB helpers
# -----------------------
def insert_entry(entry_date, event, emotion, intensity, interpretation, desire, next_action):
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "entry_date": entry_date.isoformat(),
        "event": event.strip(),
        "emotion": emotion,
        "intensity": int(intensity),
        "interpretation": (interpretation or "").strip(),
        "desire": (desire or "").strip(),
        "next_action": (next_action or "").strip(),
    }
    return supabase.table("entries").insert(payload).execute()


def delete_entry(entry_id: int):
    return supabase.table("entries").delete().eq("id", int(entry_id)).execute()


def load_entries(days=30) -> pd.DataFrame:
    since = (date.today() - timedelta(days=days)).isoformat()
    res = (
        supabase.table("entries")
        .select("id, created_at, entry_date, event, emotion, intensity, interpretation, desire, next_action")
        .gte("entry_date", since)
        .order("entry_date", desc=True)
        .order("id", desc=True)
        .execute()
    )
    data = res.data or []
    return pd.DataFrame(data)


# -----------------------
# View helpers
# -----------------------
def flow_text(row: dict) -> str:
    parts = [
        f"出来事：{row.get('event','')}",
        f"感情：{row.get('emotion','')}（強度 {row.get('intensity', '')}/10）",
        f"解釈：{row.get('interpretation','')}",
        f"欲求：{row.get('desire','')}",
        f"次の行動：{row.get('next_action','')}",
    ]
    return "\n↓\n".join([p for p in parts if p.split("：", 1)[1].strip()])


def plot_intensity(df: pd.DataFrame):
    if df.empty:
        st.info("まだデータがありません。まず1件記録してみてください。")
        return

    d = df.copy()
    # 日付をdatetimeに（entry_dateが文字列でもOK）
    d["entry_date"] = pd.to_datetime(d["entry_date"], errors="coerce")
    d["intensity"] = pd.to_numeric(d["intensity"], errors="coerce")
    d = d.dropna(subset=["entry_date", "intensity"])
    d = d.sort_values("entry_date")

    if d.empty:
        st.info("可視化できるデータがありません（日付/強度が欠損）。")
        return

    fig, ax = plt.subplots()
    ax.plot(d["entry_date"], d["intensity"], marker="o")
    ax.set_ylim(0, 10)
    ax.set_xlabel("date")
    ax.set_ylabel("intensity (0-10)")

    # 直近30日だけにズーム（空グラフ感を消す）
    start = (pd.Timestamp(date.today()) - pd.Timedelta(days=29))
    end = pd.Timestamp(date.today()) + pd.Timedelta(days=1)
    ax.set_xlim(start, end)

    # 日付目盛りを読みやすく
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=7))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.autofmt_xdate()

    # 参照線（5を目安に）
    ax.axhline(5, linewidth=1, linestyle="--")

    st.pyplot(fig)


def plot_emotion_counts(df: pd.DataFrame):
    if df.empty:
        st.info("まだデータがありません。まず1件記録してみてください。")
        return

    d = df.copy()
    d["emotion"] = d["emotion"].fillna("不明").astype(str)

    counts = d["emotion"].value_counts().sort_values(ascending=True)

    fig, ax = plt.subplots()
    ax.barh(counts.index, counts.values)  # 横棒の方が日本語に強い
    ax.set_xlabel("count")

    # 数値ラベルを付ける（地味に洗練される）
    for i, v in enumerate(counts.values):
        ax.text(v + 0.02, i, str(int(v)), va="center")

    st.pyplot(fig)



def weekly_review(df: pd.DataFrame, days: int = 7):
    if df.empty:
        return None
    d = df.copy()
    d["entry_date"] = pd.to_datetime(d["entry_date"]).dt.date
    since = date.today() - timedelta(days=days - 1)
    w = d[d["entry_date"] >= since]
    if w.empty:
        return {
            "since": since, "days": days, "num_records": 0, "num_days": 0,
            "top_emotion": None, "avg_intensity": None
        }
    num_records = int(len(w))
    num_days = int(pd.Series(w["entry_date"]).nunique())
    top_emotion = w["emotion"].value_counts().idxmax()
    avg_intensity = float(pd.to_numeric(w["intensity"], errors="coerce").dropna().mean())
    return {
        "since": since, "days": days, "num_records": num_records, "num_days": num_days,
        "top_emotion": top_emotion, "avg_intensity": avg_intensity
    }


def next_action_list(df: pd.DataFrame, max_items: int = 8) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["next_action"] = d["next_action"].fillna("").astype(str).str.strip()
    d = d[d["next_action"] != ""]
    if d.empty:
        return pd.DataFrame()
    # 最新順（すでに load_entries で desc）
    return d.head(max_items)


# -----------------------
# App
# -----------------------
st.title("🧠 思考が見える日記")
st.caption("出来事 → 感情 → 解釈 → 欲求 → 次の行動 を1分で整理")

# data
df = load_entries(days=30)

# 2 columns: input / dashboard
left, right = st.columns([1.05, 0.95], gap="large")

# -----------------------
# Left: Input
# -----------------------
with left:
    st.markdown("## ✍️ 今日の記録")

    st.markdown('<div class="card">', unsafe_allow_html=True)
    with st.form("entry_form", clear_on_submit=True):
        entry_date = st.date_input("日付", value=date.today())
        event = st.text_area("出来事（何があった？）", height=110, placeholder="例：課題が終わらなくて焦った")
        emotion = st.selectbox("感情（何を感じた？）", EMOTIONS, index=5 if "疲れ" in EMOTIONS else 0)
        intensity = st.slider("感情の強度（0〜10）", 0, 10, 6)
        interpretation = st.text_area("解釈（どういう意味だと思った？）", height=80, placeholder="例：準備不足で詰んだ気がする")
        desire = st.text_area("欲求（本当はどうしたい？）", height=80, placeholder="例：余裕を持って終わらせたい")
        next_action = st.text_input("次の行動（小さく具体的に）", placeholder="例：今日19:00〜19:30で課題の最初の1問だけやる")
        submitted = st.form_submit_button("保存")

    if submitted:
        if not event.strip():
            st.error("出来事は必須です。")
        else:
            res = insert_entry(entry_date, event, emotion, intensity, interpretation, desire, next_action)
            if getattr(res, "error", None):
                st.error(f"保存に失敗: {res.error}")
            else:
                st.success("保存しました。")
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# -----------------------
# Right: Weekly / Next Actions / Recent
# -----------------------
with right:
    st.markdown("## 📌 ダッシュボード")

    # weekly review
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 📅 今週のふりかえり（7日）")
    summary = weekly_review(df, days=7)
    if summary and summary["num_records"] > 0:
        c1, c2, c3 = st.columns(3)
        c1.metric("記録日数", f"{summary['num_days']}日")
        c2.metric("最多の感情", summary["top_emotion"])
        c3.metric("平均強度", f"{summary['avg_intensity']:.1f}/10")
        st.markdown(f"<div class='small'>対象期間：{summary['since'].isoformat()} 〜 {date.today().isoformat()}</div>", unsafe_allow_html=True)
    else:
        st.caption("直近7日分の記録がまだありません。記録するとここにサマリが表示されます。")

    st.markdown("---")

    # next actions (LIST view: readable)
    st.markdown("### ▶ 次の行動リスト")
    na = next_action_list(df, max_items=8)
    if na is None or na.empty:
        st.caption("まだ「次の行動」が書かれた記録がありません。左の入力で書くとここに集まります。")
    else:
        for _, r in na.iterrows():
            action = str(r.get("next_action", "")).strip()
            if not action:
                continue
            d = r.get("entry_date", "")
            emo = r.get("emotion", "")
            inten = r.get("intensity", "")
            st.markdown(f"- **{action}**  \n  <span class='small'>{d} / {emo}（{inten}/10）</span>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("## 📚 最近の記録（30日）")
    if df.empty:
        st.info("まだ記録がありません。左から1件保存すると表示されます。")
    else:
        show_df = df[["id", "entry_date", "emotion", "intensity", "event"]].copy()
        show_df.rename(columns={"entry_date": "日付", "emotion": "感情", "intensity": "強度", "event": "出来事"}, inplace=True)
        st.dataframe(show_df, use_container_width=True, height=260)

# -----------------------
# Detail / Charts (collapse to avoid vertical wall)
# -----------------------
st.markdown("## 🔎 詳細")

if df.empty:
    st.caption("記録を追加すると、詳細表示と可視化が使えます。")
else:
    ids = df["id"].tolist()
    selected_id = st.selectbox("表示するIDを選択", ids, index=0)

    row = df[df["id"] == selected_id].iloc[0].to_dict()

    with st.expander("🧠 思考フロー（1件表示）", expanded=True):
        # delete
        col_a, col_b = st.columns([1, 5])
        with col_a:
            confirm = st.checkbox("このIDを削除する", value=False)
        with col_b:
            if st.button("削除（取り消し不可）", disabled=not confirm):
                del_res = delete_entry(selected_id)
                if getattr(del_res, "error", None):
                    st.error(f"削除に失敗: {del_res.error}")
                else:
                    st.success(f"ID {selected_id} を削除しました。")
                    st.rerun()

        st.text(flow_text(row))

    with st.expander("📊 可視化（30日）", expanded=False):
        days = st.selectbox("表示期間", [7, 14, 30, 60, 90], index=2)
        df_viz = load_entries(days=days)
        c1, c2 = st.columns(2)
        with c1:
            st.caption("感情強度の推移")
            plot_intensity(df)
        with c2:
            st.caption("感情カテゴリの回数")
            plot_emotion_counts(df)

st.divider()
st.caption("Supabase（PostgreSQL）に保存することで、アプリが休止してもデータが消えない永続化を実現しています。")
