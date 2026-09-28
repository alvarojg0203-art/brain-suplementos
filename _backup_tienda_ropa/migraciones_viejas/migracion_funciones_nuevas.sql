-- Migración: reseñas de clientes, cupones de descuento, "avisame cuando
-- haya stock" y costo de envío real por zona.
-- Corré esto una sola vez en MySQL Workbench, sobre la base caro_boutique.

USE caro_boutique;

CREATE TABLE IF NOT EXISTS product_reviews (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  customer_id INT NOT NULL,
  rating TINYINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
  UNIQUE KEY uq_review_customer_product (customer_id, product_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS coupons (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(40) NOT NULL UNIQUE,
  percent_off DECIMAL(5,2) NOT NULL CHECK (percent_off > 0 AND percent_off <= 100),
  active TINYINT(1) NOT NULL DEFAULT 1,
  expires_at DATE,
  usage_limit INT,
  used_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

ALTER TABLE orders ADD COLUMN coupon_code VARCHAR(40) AFTER mp_payment_id;
ALTER TABLE orders ADD COLUMN discount_amount DECIMAL(10,2) AFTER coupon_code;

CREATE TABLE IF NOT EXISTS stock_notify_requests (
  id INT AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(150) NOT NULL,
  product_id INT NOT NULL,
  product_color_id INT,
  product_size_id INT,
  notified TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  FOREIGN KEY (product_color_id) REFERENCES product_colors(id) ON DELETE CASCADE,
  FOREIGN KEY (product_size_id) REFERENCES product_sizes(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS shipping_zones (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  price DECIMAL(10,2) NOT NULL DEFAULT 0,
  free_from DECIMAL(10,2),
  active TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
