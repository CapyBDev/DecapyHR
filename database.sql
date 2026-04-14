CREATE DATABASE claim_db;

-- connect to claim_db first

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(100),
    password TEXT,
    role VARCHAR(20)
);

CREATE TABLE claims (
    id SERIAL PRIMARY KEY,
    user_id INT,
    title VARCHAR(255),
    amount DECIMAL,
    category VARCHAR(100),
    status VARCHAR(20) DEFAULT 'Pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    receipt VARCHAR(255),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

INSERT INTO users (name,email,password,role)
VALUES 
('Admin','admin@test.com','123','admin'),
('User','user@test.com','123','employee');