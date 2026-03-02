-- 003_create_orders.sql
-- PURPOSE: Verify executor halts.
-- EXPECTED BEHAVIOR: Executor halts. 'orders' must not exist.

CREATE TABLE orderstwo (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    amount DECIMAL(10, 2) NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;
