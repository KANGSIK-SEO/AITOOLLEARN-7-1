-- 대화 로그 확인용 SQL (Turso 셸 `turso db shell <db>` 또는 sqlite3 로 실행)

-- 1) 최근 대화 20건 (사용자·질문·상태·지연시간)
SELECT c.id, u.email, c.created_at, c.status, c.error_code, c.latency_ms, c.question
FROM chats c JOIN users u ON u.id = c.user_id
ORDER BY c.id DESC LIMIT 20;

-- 2) 사용자별 질문 수와 실패 수
SELECT u.email, COUNT(*) AS total, SUM(c.status = 'error') AS errors
FROM chats c JOIN users u ON u.id = c.user_id
GROUP BY u.id ORDER BY total DESC;

-- 3) 오류 유형 분포 (AI_TIMEOUT 등)
SELECT error_code, COUNT(*) AS n FROM chats WHERE status = 'error' GROUP BY error_code;
