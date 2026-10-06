/* 삼성 TV 리모컨 키를 논리 액션(up/down/left/right/ok/back)으로 바꿔서
 * 현재 화면이 등록한 핸들러(window.activeScreenHandler)로 넘긴다.
 * 방향키·Enter·Return(Back)은 Tizen에서 별도 권한·등록 없이 기본으로 들어온다. */
function keyToAction(e) {
    if (e.keyCode === 10009 || e.key === "Back") return "back";
    switch (e.key) {
        case "ArrowUp": return "up";
        case "ArrowDown": return "down";
        case "ArrowLeft": return "left";
        case "ArrowRight": return "right";
        case "Enter": return "ok";
        default: return null;
    }
}

window.activeScreenHandler = null;

document.addEventListener("keydown", (e) => {
    const action = keyToAction(e);
    if (!action) return;
    // 입력창에 포커스가 있을 때 Enter는 가상 키보드 확인으로 동작하게 두고,
    // 방향키/Back만 앱이 가로챈다(텍스트 커서 이동과 충돌하지 않도록).
    const isTyping = document.activeElement && document.activeElement.tagName === "INPUT";
    if (isTyping && (action === "left" || action === "right")) return;
    if (typeof window.activeScreenHandler === "function") {
        window.activeScreenHandler(action, e);
    }
});
