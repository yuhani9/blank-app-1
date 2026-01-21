import sqlite3
from datetime import datetime, date, timedelta

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

DB_PATH = "diary.db"

EMOTIONS = ["嬉しい", "安心", "怒り", "不安", "悲しい", "疲れ", "焦り", "ワクワク", "無感情", "その他"]

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def delete_entry(entry_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM entries WHERE id = ?", (int(entry_id),))
    conn.commit()
    conn.close()


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            event TEXT NOT NULL,
            emotion TEXT NOT NULL,
            intensity INTEGER NOT NULL,
            interpretation TEXT,
            desire TEXT,
            next_action TEXT
        )
        """
    )
    conn.commit()
    conn.close()

def insert_entry(entry_date, event, emotion, intensity, interpretation, desire, next_action):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO entries (created_at, entry_date, event, emotion, intensity, interpretation, desire, next_action)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(timespec="seconds"),
            entry_date.isoformat(),
            event.strip(),
            emotion,
            int(intensity),
            (interpretation or "").strip(),
            (desire or "").strip(),
            (next_action or "").strip(),
        ),
    )
    conn.commit()
    conn.close()

def load_entries(days=30):
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM entries WHERE entry_date >= ? ORDER BY entry_date DESC, id DESC",
        conn,
        params=(since,),
    )
    conn.close()
    return df

def flow_text(row):
    # 最小の“可視化”：一目で流れが分かる表現
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

# ---------- App ----------
st.set_page_config(page_title="思考が見える日記（MVP）", layout="wide")
st.title("思考が見える日記（MVP）")

init_db()

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
            insert_entry(entry_date, event, emotion, intensity, interpretation, desire, next_action)
            st.success("保存しました。")

with right:
    st.subheader("2) 最近の記録")
    df = load_entries(days=30)

    if df.empty:
        st.info("まだ記録がありません。左から1件保存すると表示されます。")
    else:
        # 一覧（見やすさ優先で必要列だけ）
        show_df = df[["id", "entry_date", "emotion", "intensity", "event"]].copy()
        show_df.rename(
            columns={"entry_date": "日付", "emotion": "感情", "intensity": "強度", "event": "出来事"},
            inplace=True
        )
        st.dataframe(show_df, use_container_width=True, height=260)

        # 選択 → 思考フロー表示
        st.subheader("3) 思考フロー（1件表示）")
        ids = df["id"].tolist()
        selected_id = st.selectbox("表示するIDを選択", ids, index=0)

        # ここから追加
        col_a, col_b = st.columns([1, 3])
        with col_a:
            confirm = st.checkbox("このIDを削除する", value=False)
        with col_b:
            if st.button("削除（取り消し不可）", disabled=not confirm):
                delete_entry(selected_id)
                st.success(f"ID {selected_id} を削除しました。")
                st.rerun()
        # ここまで追加

        row = df[df["id"] == selected_id].iloc[0].to_dict()
        st.text(flow_text(row))


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
st.caption("MVP：入力 → 保存 → 一覧 → 1件フロー → 集計まで。永続化を強くしたい場合は外部DBに差し替えます。")

