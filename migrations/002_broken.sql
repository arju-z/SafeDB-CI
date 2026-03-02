-- 002_broken.sql
-- PURPOSE: Expose MySQL's dangerous DDL implicit commit behavior.
-- EXPECTED BEHAVIOR: 
-- 1. `CREATE TABLE roles` executes. In MySQL, any DDL statement IMMEDIATELY and implicitly commits the current transaction.
-- 2. The invalid syntax throws an error.
-- 3. Your `MySQLAdapter` except block catches the error and runs `conn.rollback()`.
-- AFTER FAILURE EXPECTATION: The `conn.rollback()` command will do absolutely NOTHING to undo the table creation. The 'roles' table WILL exist in the database, resulting in a partially applied migration. This leaves the database in a corrupted/drifted state.

CREATE TABLE rolestwo (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL
) ENGINE=InnoDB;

-- This will throw an error, but the DDL above is already committed.
CRITICAL SYNTAX ERROR DESIGNED TO FAIL;
