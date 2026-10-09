// 권리 근거 기록 페이지의 버튼·보관 상태 확인 (보안 정책 CSP 때문에 페이지 안 스크립트를 이 파일로 뺐다).
// 기록 번호와 '보관 진행 중' 여부는 페이지의 data- 속성에서 읽는다.
const info = document.getElementById("record-info");
const ARCHIVE_API = info ? info.dataset.archiveApi : null;

const printBtn = document.getElementById("print-btn");
if (printBtn) printBtn.addEventListener("click", () => window.print());

const retry = document.getElementById("retry");
if (retry && ARCHIVE_API) retry.addEventListener("click", async () => {
  retry.disabled = true; retry.textContent = "보관 요청 중…";
  await fetch(ARCHIVE_API, { method: "POST" });
  location.reload();
});

// 진행 중인 보관이 있으면 15초마다 최대 10분 동안 확인하고, 상태가 바뀌면 페이지를 새로 그린다
if (ARCHIVE_API && info.dataset.pending === "true") {
  let tries = 0;
  const poll = async () => {
    tries += 1;
    try {
      const res = await fetch(ARCHIVE_API, { method: "POST" });
      const data = await res.json();
      const still = (data.archives || []).some(a => a.requested_at && !a.archived_url && !a.error);
      if (!still) return location.reload();
    } catch (_) { /* 잠깐 실패해도 다음 확인에서 다시 본다 */ }
    if (tries < 40) setTimeout(poll, 15000);
  };
  setTimeout(poll, 15000);
}
