// 온디바이스 추천: 서버/AI 호출 없이, 브라우저에 받아둔 artworks.json(사실 데이터)을
// Datalog 스타일 규칙으로 그 자리에서 평가한다.
// 주제어가 여러 개면 "같은 머리(candidate)를 가진 규칙이 여러 개면 OR(합집합)"이라는
// 진짜 Datalog 의미론 그대로 여러 줄의 규칙으로 표현한다:
//   candidate(W) :- style(W,"Impressionism"), subject(W,"landscape"), year(W,Y), Y>=1860, Y<=1900.
//   candidate(W) :- style(W,"Impressionism"), subject(W,"spring"),    year(W,Y), Y>=1860, Y<=1900.
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

    function yearConds(filters) {
        const c = [];
        if (filters.yearFrom != null || filters.yearTo != null) {
            c.push("year(W, Y)");
            if (filters.yearFrom != null) c.push(`Y >= ${filters.yearFrom}`);
            if (filters.yearTo != null) c.push(`Y <= ${filters.yearTo}`);
        }
        return c;
    }

    function buildRuleText(filters) {
        const base = [];
        if (filters.style) base.push(`style(W, "${filters.style}")`);
        base.push(...yearConds(filters));
        const subjects = filters.subjects || [];

        if (!subjects.length) {
            if (!base.length) return "candidate(W) :- artwork(W).  % 조건을 선택하면 규칙이 채워져요";
            return `candidate(W) :- ${base.join(", ")}.`;
        }
        return subjects
            .map((s) => `candidate(W) :- ${[...base, `subject(W, "${s}")`].join(", ")}.`)
            .join("\n");
    }

    function subjectHit(work, term) {
        const kw = term.toLowerCase();
        return (work.subjects || []).some((s) => s.includes(kw) || kw.includes(s));
    }

    function matches(work, filters) {
        if (filters.style && work.style !== filters.style) return false;
        const subjects = filters.subjects || [];
        if (subjects.length && !subjects.some((s) => subjectHit(work, s))) return false;
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

    // ---- 키워드 사전 기반 자연어 "이해" (AI 없음) ----
    // LLM 없이, 문장에 이 단어가 들어있으면 이 조건이라고 정해둔 규칙표일 뿐이다.
    // 복잡한 문장은 당연히 놓칠 수 있다 — 그게 AI 이해와의 핵심 차이.
    const STYLE_ALIASES = [
        ["인상주의", "Impressionism"], ["인상파", "Impressionism"],
        ["후기인상주의", "Post-Impressionism"], ["후기 인상파", "Post-Impressionism"],
        ["사실주의", "Realism"], ["리얼리즘", "Realism"],
        ["르네상스", "Renaissance"],
        ["바로크", "Baroque"],
        ["매너리즘", "Mannerism"],
        ["신고전주의", "Neoclassicism"], ["고전주의", "Neoclassicism"],
        ["점묘법", "Pointillism"], ["점묘파", "Pointillism"],
        ["민속미술", "Folk Art"], ["민속 예술", "Folk Art"],
        ["현대미술", "Modernism"], ["모더니즘", "Modernism"],
        ["중세", "medieval"], ["고대", "ancient"],
        ["일본풍", "Japanese (culture or style)"], ["일본", "Japanese (culture or style)"],
        ["중국풍", "Chinese (culture or style)"], ["중국", "Chinese (culture or style)"],
        ["한국풍", "Korean (culture or style)"], ["한국", "Korean (culture or style)"],
        ["이슬람", "Islamic (culture or style)"],
        ["플랑드르", "Flemish"],
        ["네덜란드", "dutch"],
        ["프랑스", "france"],
        ["유럽", "european"],
    ];
    const SUBJECT_ALIASES = [
        ["풍경화", "landscape"], ["풍경", "landscape"],
        ["초상화", "portrait"], ["인물화", "portrait"],
        ["정물화", "still life"],
        ["꽃그림", "flowers"], ["꽃", "flowers"],
        ["바다", "sea"], ["바닷가", "sea"], ["해변", "sea"],
        ["산", "mountain"],
        ["봄", "spring"], ["여름", "summer"], ["가을", "autumn"], ["겨울", "winter"],
        ["숲", "forest"], ["강", "river"],
        ["종교화", "religious"], ["종교", "religious"],
        ["신화", "mythology"],
        ["동물", "animal"],
        ["누드", "nude"],
        ["전쟁", "war"],
        ["인물", "figure"],
    ];

    function parseFreeText(text) {
        const lower = text.toLowerCase();
        const matchedTerms = [];
        let style = null;
        for (const [ko, en] of STYLE_ALIASES) {
            if (lower.includes(ko.toLowerCase())) { style = en; matchedTerms.push([ko, en]); break; }
        }
        const subjects = [];
        for (const [ko, en] of SUBJECT_ALIASES) {
            if (lower.includes(ko.toLowerCase()) && !subjects.includes(en)) {
                subjects.push(en);
                matchedTerms.push([ko, en]);
            }
        }
        let yearFrom = null, yearTo = null;
        const century = text.match(/(\d{1,2})\s*세기/);
        if (century) {
            const c = Number(century[1]);
            yearFrom = (c - 1) * 100 + 1;
            yearTo = c * 100;
            matchedTerms.push([century[0], `${yearFrom}-${yearTo}`]);
        } else {
            const year = text.match(/\b(1[0-9]{3}|20[0-2][0-9])\b/);
            if (year) {
                const y = Number(year[1]);
                yearFrom = y - 10;
                yearTo = y + 10;
                matchedTerms.push([year[0], `${yearFrom}-${yearTo}`]);
            }
        }
        return { style, subjects, yearFrom, yearTo, matchedTerms };
    }

    window.OnDevice = { loadFacts, buildRuleText, evalRule, styleOptions, parseFreeText };
})();
