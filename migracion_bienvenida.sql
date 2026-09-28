-- Migración para el popup de bienvenida (nombre/mail/cumpleaños a cambio
-- de un cupón de descuento en la primera compra, como en Proteviking).
-- Es seguro correrlo: sólo crea la tabla nueva y, si todavía no existe,
-- un cupón "BIENVENIDA10" de 10% sin vencimiento ni límite de usos (lo
-- podés editar o borrar después desde Admin → Cupones).
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS welcome_signups (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(150) NOT NULL,
  email VARCHAR(150) NOT NULL,
  birthday DATE,
  coupon_code VARCHAR(40),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_welcome_email (email)
) ENGINE=InnoDB;

INSERT IGNORE INTO coupons (code, percent_off, active) VALUES ('BIENVENIDA10', 10, 1);
