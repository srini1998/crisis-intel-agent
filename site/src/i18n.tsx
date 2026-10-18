import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Lang = "en" | "ja";

const STRINGS = {
  en: {
    navLive: "Live map",
    navHow: "How it works",
    navSources: "Sources",
    heroTitle: "What is happening right now, in plain language.",
    heroSub: "Reports and alerts from four public agencies, grouped into incidents with explicit citation and number checks.",
    heroCta: "Open the live map",
    heroSecondary: "How briefs are checked",
    liveTitle: "Recent and active incidents",
    loading: "Fetching official feeds",
    feedFailed: "unavailable",
    filterAll: "All",
    hazards: { earthquake: "Earthquakes", cyclone: "Storms", wildfire: "Wildfires", volcano: "Volcanoes", flood: "Floods", drought: "Drought", severe_weather: "US weather alerts", ice: "Sea ice", other: "Other" } as Record<string, string>,
    sourcesCount: (n: number) => `${n} source${n === 1 ? "" : "s"}`,
    pick: "Pick an incident on the map or in the list.",
    briefTemplate: "Quick summary",
    briefTemplateNote: "Built directly from the publishers' structured fields.",
    briefModel: "AI briefing",
    briefModelNote: "Drafted on your device, then checked for citations, numbers and alert level. Statements still need review.",
    writeBrief: "Write AI briefing",
    loadModel: "Download the AI (about 860 MB, once)",
    modelLoading: "Downloading the model to your browser",
    modelReady: (d: string) => `Model ready on ${d === "webgpu" ? "your GPU" : "your CPU"}`,
    writing: "Writing",
    alert: "Alert level",
    alertMismatch: (e: string) => `Sources say ${e}`,
    verified: "Citation and number checks passed; review the statements",
    partly: "Some citation or number checks failed",
    rejected: "Claims that failed the check",
    sourcesTitle: "Sources for this incident",
    watch: "What to watch",
    howTitle: "Every statement needs a citation. Numbers must occur in it. This is not a truth check.",
    howSteps: [
      ["Collect", "Your browser fetches USGS, GDACS, NASA EONET and US National Weather Service feeds directly. Nothing passes through a server of ours."],
      ["Group", "Reports from different agencies about the same event are joined when the hazard, place and time agree. Earthquakes must also agree on magnitude."],
      ["Write", "A small open model runs on your device and drafts a short briefing from the numbered source documents."],
      ["Check", "Each claim must cite a document and every number must appear in it. The alert level must equal the highest official level. Text that tries to instruct the model is removed first."],
    ],
    sourcesHeading: "Where the data comes from",
    limits: "Not an official warning service. Briefings repeat what the publishers say; they do not estimate casualties or forecast. Checks confirm citations and numbers, not truth.",
    trace: "Agent trace",
    traceTitle: "What the agent did",
    traceEmpty: "Run an AI briefing to see the prompt, the raw output and every check here.",
    traceFeeds: "Feed requests",
    tracePrompt: "Prompt sent to the model (after sanitizing)",
    traceRaw: "Raw model output",
    traceChecks: "Checks",
    traceRemoved: "Removed as instruction-like text",
    close: "Close",
    footer: "Built by Srinivas Venigalla. Open source, runs in your browser, no tracking.",
    updated: (t: string) => `Updated ${t}`,
    refresh: "Refresh",
    lang: "日本語",
  },
  ja: {
    navLive: "ライブマップ",
    navHow: "しくみ",
    navSources: "情報源",
    heroTitle: "いま世界で起きていることを、わかりやすい言葉で。",
    heroSub: "4つの公的機関の発表を出来事ごとにまとめ、出典・数値・警戒レベルを照合します。",
    heroCta: "ライブマップを開く",
    heroSecondary: "照合のしくみ",
    liveTitle: "最近・継続中の出来事",
    loading: "公式フィードを取得しています",
    feedFailed: "取得できません",
    filterAll: "すべて",
    hazards: { earthquake: "地震", cyclone: "暴風・台風", wildfire: "山火事", volcano: "火山", flood: "洪水", drought: "干ばつ", severe_weather: "米国の気象警報", ice: "海氷", other: "その他" } as Record<string, string>,
    sourcesCount: (n: number) => `情報源 ${n} 件`,
    pick: "地図または一覧から出来事を選んでください。",
    briefTemplate: "簡易サマリー",
    briefTemplateNote: "発表機関の構造化データからそのまま作成しています。",
    briefModel: "AIブリーフィング",
    briefModelNote: "端末上のモデルが作成し、出典・数値・警戒レベルを照合。記述自体の確認は必要です。",
    writeBrief: "AIブリーフィングを作成",
    loadModel: "AIをダウンロード（約860MB・初回のみ）",
    modelLoading: "モデルをブラウザにダウンロード中",
    modelReady: (d: string) => `モデル準備完了（${d === "webgpu" ? "GPU" : "CPU"}で実行）`,
    writing: "作成中",
    alert: "警戒レベル",
    alertMismatch: (e: string) => `出典では ${e}`,
    verified: "出典・数値の照合に合格。記述自体は要確認",
    partly: "出典または数値の照合に失敗しました",
    rejected: "照合に失敗した記述",
    sourcesTitle: "この出来事の情報源",
    watch: "今後の注目点",
    howTitle: "記述には出典が必要で、数値はそこに含まれる必要があります。真偽の判定ではありません。",
    howSteps: [
      ["収集", "ブラウザがUSGS、GDACS、NASA EONET、米国立気象局のフィードを直接取得します。当サイトのサーバーは経由しません。"],
      ["統合", "同じ出来事に関する複数機関の報告を、災害の種類・場所・時刻が一致する場合にまとめます。地震はマグニチュードも一致が必要です。"],
      ["作成", "お使いの端末上で小型のオープンモデルが動き、番号付きの出典から短いブリーフィングを作成します。"],
      ["照合", "各記述は出典を引用し、すべての数値がその出典に含まれている必要があります。警戒レベルは公式の最高レベルと一致しなければなりません。モデルへの指示を装った文は事前に除去します。"],
    ],
    sourcesHeading: "データの出どころ",
    limits: "公式の警報サービスではありません。ブリーフィングは発表機関の内容を伝えるもので、被害の推定や予測は行いません。照合は引用と数値の一致を確認するもので、事実の正しさを保証するものではありません。",
    trace: "エージェント記録",
    traceTitle: "エージェントの動作記録",
    traceEmpty: "AIブリーフィングを作成すると、プロンプト・生の出力・照合結果がここに表示されます。",
    traceFeeds: "フィード取得",
    tracePrompt: "モデルに送ったプロンプト（無害化後）",
    traceRaw: "モデルの生の出力",
    traceChecks: "照合結果",
    traceRemoved: "指示文として除去された文",
    close: "閉じる",
    footer: "制作：Srinivas Venigalla。オープンソース、ブラウザ内で動作、トラッキングなし。",
    updated: (t: string) => `${t} 更新`,
    refresh: "再取得",
    lang: "English",
  },
};

export type Strings = (typeof STRINGS)["en"];
const Ctx = createContext<{ lang: Lang; t: Strings; toggle: () => void }>({ lang: "en", t: STRINGS.en, toggle: () => {} });

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>(() => {
    try {
      return (localStorage.getItem("lang") as Lang) === "ja" ? "ja" : "en";
    } catch {
      return "en";
    }
  });
  useEffect(() => {
    document.documentElement.lang = lang;
    try {
      localStorage.setItem("lang", lang);
    } catch {
      /* storage may be unavailable */
    }
  }, [lang]);
  return <Ctx.Provider value={{ lang, t: STRINGS[lang] as Strings, toggle: () => setLang((l) => (l === "en" ? "ja" : "en")) }}>{children}</Ctx.Provider>;
}

export const useT = () => useContext(Ctx);
