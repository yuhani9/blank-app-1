from datetime import datetime, date, timedelta

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from supabase import create_client
from postgrest.exceptions import APIError

EMOTIONS = ["嬉しい", "安心", "怒り", "不安", "悲しい", "疲れ", "焦り", "ワクワク", "無感情", "その他"]


@st.cache_resource
def get_supabase():
    cfg = st.secrets["connections"]["supabase"]
    return create_client(cfg["SUPABASE_URL"], cfg["SUPABASE_KEY"])


supabase = get_supabase()


def delete_entry(entry_id: int):
    try:
        supabase.table("entries").delete().eq("id", int(entry_id)).execute()
    except APIError as e:
        st.error("削除に失敗（Supabase）")
        st.code(str(e))
        raise


def insert_entry(entry_date, event, emotion, intensity, interpretation, desire, next_action):
    payload = {
        # created_at はDB側で now() を使うので送らなくてもOK
        "entry_date": entry_date.isoformat(),
        "event": event.strip(),
        "emotion": emotion,
        "intensity": int(intensity),
        "interpretation": (interpretation or "").strip(),
        "desire": (desire or "").strip(),
        "next_action": (next_action or "").strip(),
    }
    try:
        supabase.table("entries").insert(payload).execute()
    except APIError as e:
        st.error("保存に失敗（Supabase）")
        st.code(str(e))
        raise


def load_entries(days=30) -> pd.DataFrame:
    since = (date.today() - timedelta(days=days)).isoformat()
    try:
        res = (
            supabase
            .table("entries")
            .select("id, created_at, entry_date, event, emotion, intensity, interpretation, desire, next_action")
            .gte("entry_date", since)
            .order("entry_date", desc=True)
            .order("id", desc=True)
            .execute()
        )
    except APIError as e:
        st.error("読み込みに失敗（Supabase）")
        st.code(str(e))
        return pd.DataFrame()

    return pd.DataFrame(res.data or [])


def flow_text(row):
    parts = [
        f"出来事：{row.get('event','')}",
        f"感情：{row.get('emotion','')}（強度 {row.get('intensity', '')}/10）",
        f"解釈：{row.get('interpretation','')}",
        f"欲求：{row.get('desire','')}",
        f"次の行動：{row.get('next_action','')}",
    ]
    return "\n↓\n".join([p for p in parts if p.split("：", 1)[1].strip()])


def plot_intensity(df):
    if df.empty:
        st.info("まだデータがありません。まず1件記録してみてください。")
        return
    d = df.copy()
    d["entry_date"] = pd.to_datetime(d["entry_date"])
    d = d.sort_values("entry_date")
    fig = plt.figure()
    plt.plot(d["entry_date"], d["intensity"])
    plt.ylim(0, 10)
    plt.xlabel("date")
    plt.ylabel("intensity (0-10)")
    st.pyplot(fig)


def plot_emotion_counts(df):
    if df.empty:
        return
    counts = df["emotion"].value_counts().sort_values(ascending=False)
    fig = plt.figure()
    plt.bar(counts.index, counts.values)
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("count")
    st.pyplot(fig)

def weekly_review(df: pd.DataFrame, days: int = 7):
    """直近days日分のサマリを返す（記録日数・最多感情・平均強度）"""
    if df.empty:
        return None

    d = df.copy()
    d["entry_date"] = pd.to_datetime(d["entry_date"]).dt.date

    since = date.today() - timedelta(days=days - 1)
    w = d[d["entry_date"] >= since]

    if w.empty:
        return {
            "since": since,
            "days": days,
            "num_records": 0,
            "num_days": 0,
            "top_emotion": None,
            "avg_intensity": None,
        }

    num_records = int(len(w))
    num_days = int(pd.Series(w["entry_date"]).nunique())
    top_emotion = w["emotion"].value_counts().idxmax()
    avg_intensity = float(pd.to_numeric(w["intensity"], errors="coerce").dropna().mean())

    return {
        "since": since,
        "days": days,
        "num_records": num_records,
        "num_days": num_days,
        "top_emotion": top_emotion,
        "avg_intensity": avg_intensity,
    }


def next_action_list(df: pd.DataFrame, max_items: int = 8) -> pd.DataFrame:
    """next_action が空でないものを抽出して返す（最新順）"""
    if df.empty:
        return pd.DataFrame(columns=["entry_date", "emotion", "intensity", "next_action", "event"])

    d = df.copy()
    d["next_action"] = d["next_action"].fillna("").astype(str).str.strip()
    d = d[d["next_action"] != ""]

    if d.empty:
        return pd.DataFrame(columns=["entry_date", "emotion", "intensity", "next_action", "event"])

    # 最新順（entry_date desc, id desc になっている想定）
    cols = ["entry_date", "emotion", "intensity", "next_action", "event", "id"]
    cols = [c for c in cols if c in d.columns]
    d = d[cols].head(max_items)

    return d


# ---------- App ----------
st.set_page_config(page_title="思考が見える日記", layout="wide")
st.markdown("""
<style>
/* 全体の余白と最大幅 */
.block-container {max-width: 1200px; margin: auto;}

/* 見出しの詰まりを改善 */
h1, h2, h3 {letter-spacing: -0.02em;}

/* フォームをカード化 */
div[data-testid="stForm"] {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  padding: 18px 18px 6px 18px;
  box-shadow: 0 8px 24px rgba(17,24,39,0.06);
}

/* 右側の「最近の記録」もカードっぽく */
section[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stDataFrame"]) {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  padding: 14px;
}

/* infoバーの青を弱める */
div[data-testid="stAlert"] {
  border-radius: 12px;
}
</style>
""", unsafe_allow_html=True)


st.title("思考が見える日記")

left, right = st.columns([1, 1])

with left:
    st.subheader("1) 今日の記録")
    with st.form("entry_form", clear_on_submit=True):
        entry_date = st.date_input("日付", value=date.today())
        event = st.text_area("出来事（何があった？）", height=120, placeholder="例：課題が終わらなくて焦った")
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
            try:
                insert_entry(entry_date, event, emotion, intensity, interpretation, desire, next_action)
                st.success("保存しました。")
                st.rerun()
            except APIError:
                pass

with right:
    st.subheader("2) 最近の記録")
    df = load_entries(days=30)

    if df.empty:
        st.info("まだ記録がありません。左から1件保存すると表示されます。")
    else:
        st.subheader("📅 今週のふりかえり（7日）")
        summary = weekly_review(df, days=7)

        if summary and summary["num_records"] > 0:
            c1, c2, c3 = st.columns(3)
            c1.metric("記録日数", f"{summary['num_days']}日")
            c2.metric("最多の感情", summary["top_emotion"])
            c3.metric("平均強度", f"{summary['avg_intensity']:.1f}/10")
            st.caption(f"対象期間：{summary['since'].isoformat()} 〜 {date.today().isoformat()}")
        else:
            st.caption("直近7日分の記録がまだありません。記録するとここにサマリが表示されます。")

        st.subheader("▶ 次の行動リスト")
        na = next_action_list(df, max_items=8)

        if na.empty:
            st.caption("まだ「次の行動」が書かれた記録がありません。左の入力で書くとここに集まります。")
        else:
            # 見やすい表示に整形
            show_na = na.copy()
            if "event" in show_na.columns:
                show_na["event"] = show_na["event"].astype(str).str.slice(0, 30)

            show_na = show_na[["entry_date", "next_action", "emotion", "intensity", "event"]]
            show_na.rename(
                columns={
                    "entry_date": "日付",
                    "next_action": "次の行動",
                    "emotion": "感情",
                    "intensity": "強度",
                    "event": "出来事（短縮）",
                },
                inplace=True
            )
            st.dataframe(show_na, use_container_width=True, height=220)

        st.divider()

        show_df = df[["id", "entry_date", "emotion", "intensity", "event"]].copy()
        show_df.rename(
            columns={"entry_date": "日付", "emotion": "感情", "intensity": "強度", "event": "出来事"},
            inplace=True
        )
        st.dataframe(show_df, use_container_width=True, height=260)

        st.subheader("3) 思考フロー（1件表示）")
        ids = df["id"].tolist()
        selected_id = st.selectbox("表示するIDを選択", ids, index=0)

        col_a, col_b = st.columns([1, 3])
        with col_a:
            confirm = st.checkbox("このIDを削除する", value=False)
        with col_b:
            if st.button("削除（取り消し不可）", disabled=not confirm):
                try:
                    delete_entry(selected_id)
                    st.success(f"ID {selected_id} を削除しました。")
                    st.rerun()
                except APIError:
                    pass

        row = df[df["id"] == selected_id].iloc[0].to_dict()
        st.text(flow_text(row))

        st.subheader("4) 可視化（30日）")
        c1, c2 = st.columns(2)
        with c1:
            st.caption("感情強度の推移")
            plot_intensity(df)
        with c2:
            st.caption("感情カテゴリの回数")
            plot_emotion_counts(df)

st.divider()
st.caption("入力 → Supabaseに保存 → 一覧 → 1件フロー → 集計まで。sqliteではなく外部DBで永続化。")
