-- 001_create_users.sql
-- PURPOSE: Establish baseline in MySQL.
-- CONSTRAINTS: We explicitly specify ENGINE=InnoDB, which supports transactions. (MyISAM does not).
-- EXPECTED BEHAVIOR: This executes and commits successfully.

CREATE TABLE userstwo (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
