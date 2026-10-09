// 첫 화면이 그려지기 전에 저장된 테마·언어를 적용해 깜빡임을 막는다.
// <head>에서 바로(defer 없이) 읽혀야 해서 따로 작은 파일로 둔다 — 화면 안 스크립트는 보안 정책(CSP)이 막는다.
try {
    const theme = localStorage.getItem("pd-theme");
    if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
    const lang = localStorage.getItem("pd-lang");
    if (lang === "en") document.documentElement.lang = "en";
} catch (_) { /* 저장소를 못 써도 기본값으로 동작 */ }
