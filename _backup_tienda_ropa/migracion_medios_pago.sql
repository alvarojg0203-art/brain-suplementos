CREATE TABLE IF NOT EXISTS payment_settings (
  id INT PRIMARY KEY DEFAULT 1,
  efectivo TINYINT(1) NOT NULL DEFAULT 1,
  transferencia TINYINT(1) NOT NULL DEFAULT 1,
  tarjeta_credito TINYINT(1) NOT NULL DEFAULT 1,
  tarjeta_debito TINYINT(1) NOT NULL DEFAULT 1,
  mercado_pago TINYINT(1) NOT NULL DEFAULT 1,
  tarjetas_aceptadas VARCHAR(255)
) ENGINE=InnoDB;
INSERT IGNORE INTO payment_settings (id) VALUES (1);
