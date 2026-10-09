// 오프라인용 서비스워커 등록. 화면 안에 직접 쓴 스크립트(inline)를 없애야 보안 정책(CSP)이
// '우리 서버의 스크립트 파일만 실행'으로 엄격해질 수 있어 따로 뺐다 (해커가 끼워 넣은 스크립트 차단).
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js'));
}
