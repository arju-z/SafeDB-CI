-- SCENARIO 6: NAMING HEURISTICS WARNINGS
-- 003_create_dept_projects.sql
--
-- DEFECT 4: Junction table `dept_projects` has 2 FK columns but NO composite PK.
-- The naming heuristic will flag: "Junction table missing composite PK"
--
-- Without a composite PK on (department_id, project_id), the same
-- department can be assigned to the same project multiple times — rows
-- are not uniquely keyed.

CREATE TABLE projects (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL UNIQUE
);

-- This is the broken junction table: has two FKs but no composite PK.
-- The correct definition would be:
--   PRIMARY KEY (department_id, project_id)
CREATE TABLE dept_projects (
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    assigned_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- Missing: PRIMARY KEY (department_id, project_id)
);
