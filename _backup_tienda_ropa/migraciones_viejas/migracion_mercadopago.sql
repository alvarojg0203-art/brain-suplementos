-- Si ya corriste esta parte (recuperar contraseña por mail), salteala.
ALTER TABLE customers ADD COLUMN reset_token VARCHAR(100) AFTER oauth_id;
ALTER TABLE customers ADD COLUMN reset_token_expires DATETIME AFTER reset_token;

-- Para Mercado Pago (nuevo)
ALTER TABLE orders ADD COLUMN mp_preference_id VARCHAR(100) AFTER delivery_address;
ALTER TABLE orders ADD COLUMN mp_payment_id VARCHAR(100) AFTER mp_preference_id;
