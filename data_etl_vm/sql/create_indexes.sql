-- =============================================================================
-- create_indexes.sql
--
-- This file is executed after the main data import completes.
-- Add any post-import SQL here: indexes, constraints, table renames, views, etc.
--
-- The statement timeout for this file is controlled by index_timeout_minutes
-- in config.py. Increase it if you have large tables or many indexes.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

-- B-tree index (good for equality and range queries on most column types)
-- CREATE INDEX idx_your_column ON your_table USING btree (your_column);

-- GIN trigram index (good for LIKE / ILIKE text search — requires pg_trgm)
-- CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- CREATE INDEX idx_your_text_trgm ON your_table USING gin (your_text_column gin_trgm_ops);

-- GiST spatial index (good for geometry/geography columns — requires PostGIS)
-- CREATE INDEX idx_your_geom ON your_table USING gist (your_geom_column);


-- ---------------------------------------------------------------------------
-- Post-import cleanup / finalization
-- ---------------------------------------------------------------------------

-- Rename the imported table to its final name
-- ALTER TABLE your_import_table RENAME TO your_final_table;

-- Drop a previous version of the table if this is a recurring import
-- DROP TABLE IF EXISTS your_old_table;

-- Create a view over the final table
-- CREATE OR REPLACE VIEW your_view AS
-- SELECT
--     col1,
--     col2,
--     col3
-- FROM your_final_table;
