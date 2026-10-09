-- Fabric SQL database: sqldb_goldenrecord_steward
-- Write target for the translytical task flows (fabric/functions/function_app.py). Replicated to OneLake
-- automatically; add these tables to lh_goldenrecord as shortcuts so nb_05 can read them.

CREATE TABLE dbo.pattern_decisions_inbox (
    id          INT IDENTITY(1, 1) PRIMARY KEY,
    pattern_id  VARCHAR(32)   NOT NULL,
    decision    VARCHAR(10)   NOT NULL CHECK (decision IN ('approve', 'reject')),
    canonical   NVARCHAR(200) NULL,
    note        NVARCHAR(500) NULL,
    reviewer    NVARCHAR(200) NOT NULL,
    decided_at  DATETIME2     NOT NULL
);

CREATE TABLE dbo.unmerge_inbox (
    id          INT IDENTITY(1, 1) PRIMARY KEY,
    record_key  VARCHAR(64)   NOT NULL,
    note        NVARCHAR(500) NULL,
    reviewer    NVARCHAR(200) NOT NULL,
    decided_at  DATETIME2     NOT NULL
);

CREATE TABLE dbo.rule_requests_inbox (
    id           INT IDENTITY(1, 1) PRIMARY KEY,
    rule_text    NVARCHAR(1000) NOT NULL,
    accept       BIT            NOT NULL DEFAULT 0,
    override     BIT            NOT NULL DEFAULT 0,
    reviewer     NVARCHAR(200)  NOT NULL,
    requested_at DATETIME2      NOT NULL
);
