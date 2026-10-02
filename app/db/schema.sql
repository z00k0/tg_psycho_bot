CREATE TABLE terms (
    id INTEGER PRIMARY KEY,
    term TEXT NOT NULL,
    term_normalized TEXT NOT NULL COLLATE NOCASE,
    heading TEXT NOT NULL,
    definition TEXT NOT NULL,
    redirect_to TEXT,
    letter TEXT NOT NULL CHECK (length(letter) = 1),
    search_blob TEXT NOT NULL,
    quality_flags_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(quality_flags_json)),
    UNIQUE (term_normalized)
);

CREATE INDEX idx_terms_letter ON terms (letter);

CREATE TABLE term_aliases (
    term_id INTEGER NOT NULL,
    alias_normalized TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (term_id, alias_normalized),
    FOREIGN KEY (term_id) REFERENCES terms (id) ON DELETE CASCADE
);

CREATE INDEX idx_term_aliases_alias_normalized
    ON term_aliases (alias_normalized);

CREATE VIRTUAL TABLE terms_fts USING fts5(
    term,
    heading,
    definition,
    search_blob,
    content='terms',
    content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER terms_fts_after_insert
AFTER INSERT ON terms
BEGIN
    INSERT INTO terms_fts(rowid, term, heading, definition, search_blob)
    VALUES (new.id, new.term, new.heading, new.definition, new.search_blob);
END;

CREATE TRIGGER terms_fts_after_delete
AFTER DELETE ON terms
BEGIN
    INSERT INTO terms_fts(terms_fts, rowid, term, heading, definition, search_blob)
    VALUES (
        'delete', old.id, old.term, old.heading, old.definition, old.search_blob
    );
END;

CREATE TRIGGER terms_fts_after_update
AFTER UPDATE ON terms
BEGIN
    INSERT INTO terms_fts(terms_fts, rowid, term, heading, definition, search_blob)
    VALUES (
        'delete', old.id, old.term, old.heading, old.definition, old.search_blob
    );
    INSERT INTO terms_fts(rowid, term, heading, definition, search_blob)
    VALUES (new.id, new.term, new.heading, new.definition, new.search_blob);
END;
