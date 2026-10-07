/* 화면마다 "지금 포커스된 요소가 몇 번째인가"만 들고, 화살표 키로 인덱스를 옮기는
 * 가장 단순한 포커스 매니저. 기존 코드에 적응할 D-pad 로직이 없어서 새로 만든다. */
function createFocusGroup(elements, columns = 1) {
    let index = 0;

    function apply() {
        elements.forEach((el, i) => el.classList.toggle("focused", i === index));
        const el = elements[index];
        if (el) {
            if (el.tagName === "INPUT" || el.tagName === "BUTTON") el.focus();
            if (el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
        }
    }

    function clamp(i) { return Math.max(0, Math.min(elements.length - 1, i)); }

    function move(action) {
        if (!elements.length) return;
        let next = index;
        if (action === "left") next = clamp(index - 1);
        else if (action === "right") next = clamp(index + 1);
        else if (action === "up") next = clamp(index - columns);
        else if (action === "down") next = clamp(index + columns);
        else return;
        if (next !== index) { index = next; apply(); }
    }

    function current() { return elements[index]; }

    function setIndex(i) { index = clamp(i); apply(); }

    apply();
    return { move, current, setIndex };
}
