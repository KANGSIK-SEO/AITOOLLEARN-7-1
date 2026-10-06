-- 미술 작품 DB (읽기 전용 데이터). 출처: MET Open Access(CC0), Art Institute of Chicago API(CC0).
-- 수집 스크립트: scripts/collect_met.py, scripts/collect_aic.py
--
-- 이 파일은 미술 DB(data/art.db) 전용이다. 사용자 데이터(users, chats, favorites)는
-- 별도 DB(Turso 또는 data/app.db)에 있으며 스키마는 app/db.py의 SCHEMA에 정의되어 있다.
-- favorites.artwork_id는 이 파일의 artworks.id를 가리키지만 DB가 달라 FOREIGN KEY는 없다.

CREATE TABLE IF NOT EXISTS artworks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT    NOT NULL CHECK (source IN ('met', 'aic')),
    source_id        TEXT    NOT NULL,          -- 출처 기관에서의 작품 ID
    title            TEXT    NOT NULL,
    artist           TEXT,
    artist_bio       TEXT,                      -- 예: "Dutch, Zundert 1853–1890 Auvers-sur-Oise"
    date_display     TEXT,                      -- 표기용 제작 시기
    year_start       INTEGER,
    year_end         INTEGER,
    medium           TEXT,
    classification   TEXT,
    department       TEXT,
    origin           TEXT,                      -- 제작 국가/문화권
    style            TEXT,
    subjects         TEXT,                      -- 쉼표로 구분한 주제 키워드 (landscape, flowers ...)
    image_url        TEXT    NOT NULL,          -- 큰 이미지 (공식 URL)
    thumbnail_url    TEXT,
    source_url       TEXT    NOT NULL,          -- 기관 공식 작품 페이지
    credit_line      TEXT,
    is_public_domain INTEGER NOT NULL DEFAULT 1 CHECK (is_public_domain IN (0, 1)),
    license          TEXT    NOT NULL DEFAULT 'CC0',
    is_highlight     INTEGER NOT NULL DEFAULT 0,
    collected_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_artworks_artist ON artworks (artist);
CREATE INDEX IF NOT EXISTS idx_artworks_year   ON artworks (year_start, year_end);
CREATE INDEX IF NOT EXISTS idx_artworks_pd     ON artworks (is_public_domain);

-- 자연어 질문에서 뽑은 키워드로 검색하기 위한 전문 검색 인덱스
CREATE VIRTUAL TABLE IF NOT EXISTS artworks_fts USING fts5 (
    title, artist, medium, style, subjects, origin,
    content = 'artworks', content_rowid = 'id', tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS artworks_ai AFTER INSERT ON artworks BEGIN
    INSERT INTO artworks_fts (rowid, title, artist, medium, style, subjects, origin)
    VALUES (new.id, new.title, new.artist, new.medium, new.style, new.subjects, new.origin);
END;

CREATE TRIGGER IF NOT EXISTS artworks_ad AFTER DELETE ON artworks BEGIN
    INSERT INTO artworks_fts (artworks_fts, rowid, title, artist, medium, style, subjects, origin)
    VALUES ('delete', old.id, old.title, old.artist, old.medium, old.style, old.subjects, old.origin);
END;

CREATE TRIGGER IF NOT EXISTS artworks_au AFTER UPDATE ON artworks BEGIN
    INSERT INTO artworks_fts (artworks_fts, rowid, title, artist, medium, style, subjects, origin)
    VALUES ('delete', old.id, old.title, old.artist, old.medium, old.style, old.subjects, old.origin);
    INSERT INTO artworks_fts (rowid, title, artist, medium, style, subjects, origin)
    VALUES (new.id, new.title, new.artist, new.medium, new.style, new.subjects, new.origin);
END;
