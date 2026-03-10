-- SCENARIO 6: NAMING HEURISTICS WARNINGS
-- 002_create_employees.sql
--
-- DEFECT 2: `category_list` column — name pattern suggests array/CSV storage.
-- The naming heuristic will flag: "Column name suggests array/CSV storage"
--
-- DEFECT 3: `department_id` column with FK correctly declared (this should NOT warn).
-- This demonstrates that the heuristic only flags columns WITHOUT FK constraints.

CREATE TABLE employees (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(200) NOT NULL,
    department_id INTEGER NOT NULL REFERENCES departments(id),  -- correct FK, no warning
    -- This column name strongly suggests it stores CSV skill tags like "python,sql,docker"
    -- instead of using a proper skill_tags junction table.
    category_list TEXT,
    hired_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
