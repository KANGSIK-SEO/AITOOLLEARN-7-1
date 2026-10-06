// 온디바이스 추천: 서버/AI 호출 없이, 브라우저에 받아둔 artworks.json(사실 데이터)을
// Datalog 스타일 규칙(conjunctive query, AND 조건)으로 그 자리에서 평가한다.
// candidate(W) :- style(W,S), subject(W,Kw), year(W,Y), Y>=from, Y<=to.
// 재귀가 필요한 질의가 아니라 naive bottom-up(배열 필터)으로 충분하다.
(function () {
    let factsCache = null;
    const MAX_RESULTS = 24;

    async function loadFacts() {
        if (factsCache) return factsCache;
        const res = await fetch("/static/artworks.json");
        factsCache = await res.json();
        return factsCache;
    }

    function buildRuleText(filters) {
        const conds = [];
        if (filters.style) conds.push(`style(W, "${filters.style}")`);
        if (filters.subject) conds.push(`subject(W, "${filters.subject}")`);
        if (filters.yearFrom != null) conds.push(`year(W, Y)`, `Y >= ${filters.yearFrom}`);
        if (filters.yearTo != null) {
            if (filters.yearFrom == null) conds.push(`year(W, Y)`);
            conds.push(`Y <= ${filters.yearTo}`);
        }
        if (!conds.length) return "candidate(W) :- artwork(W).  % 조건을 선택하면 규칙이 채워져요";
        return `candidate(W) :- ${conds.join(", ")}.`;
    }

    function matches(work, filters) {
        if (filters.style && work.style !== filters.style) return false;
        if (filters.subject) {
            const kw = filters.subject.toLowerCase();
            const hit = (work.subjects || []).some((s) => s.includes(kw) || kw.includes(s));
            if (!hit) return false;
        }
        if (filters.yearFrom != null && (work.year_end == null || work.year_end < filters.yearFrom)) return false;
        if (filters.yearTo != null && (work.year_start == null || work.year_start > filters.yearTo)) return false;
        return true;
    }

    function evalRule(facts, filters) {
        const out = [];
        for (const work of facts) {
            if (matches(work, filters)) {
                out.push(work);
                if (out.length >= MAX_RESULTS) break;
            }
        }
        return out;
    }

    function styleOptions(facts) {
        const counts = new Map();
        for (const w of facts) {
            if (!w.style) continue;
            counts.set(w.style, (counts.get(w.style) || 0) + 1);
        }
        return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([style]) => style);
    }

    window.OnDevice = { loadFacts, buildRuleText, evalRule, styleOptions };
})();
