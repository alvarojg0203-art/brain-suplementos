-- Migración: sistema de gestión / caja para ventas presenciales en el local.
-- Corré esto una sola vez en MySQL Workbench sobre la base caro_boutique.

ALTER TABLE products ADD COLUMN cost_price DECIMAL(10,2) NULL AFTER discount_percent;

CREATE TABLE IF NOT EXISTS cash_registers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  opened_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  opening_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
  closed_at TIMESTAMP NULL,
  closing_amount DECIMAL(10,2),
  expected_amount DECIMAL(10,2),
  difference DECIMAL(10,2),
  notes VARCHAR(255),
  status ENUM('abierta','cerrada') NOT NULL DEFAULT 'abierta'
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pos_sales (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cash_register_id INT NOT NULL,
  total DECIMAL(10,2) NOT NULL,
  payment_method VARCHAR(50) NOT NULL DEFAULT 'Efectivo',
  customer_name VARCHAR(150),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (cash_register_id) REFERENCES cash_registers(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pos_sale_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  sale_id INT NOT NULL,
  product_id INT,
  product_name VARCHAR(150) NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  qty INT NOT NULL CHECK (qty > 0),
  product_color_id INT,
  color_name VARCHAR(60),
  product_size_id INT,
  size_name VARCHAR(20),
  FOREIGN KEY (sale_id) REFERENCES pos_sales(id) ON DELETE CASCADE,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
  FOREIGN KEY (product_color_id) REFERENCES product_colors(id) ON DELETE SET NULL,
  FOREIGN KEY (product_size_id) REFERENCES product_sizes(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS cash_expenses (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cash_register_id INT,
  category VARCHAR(60) NOT NULL DEFAULT 'Otro',
  description VARCHAR(255),
  amount DECIMAL(10,2) NOT NULL CHECK (amount >= 0),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (cash_register_id) REFERENCES cash_registers(id) ON DELETE SET NULL
) ENGINE=InnoDB;
