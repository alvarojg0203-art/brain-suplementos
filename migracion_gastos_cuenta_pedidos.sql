-- Migración grande: agrega todo lo necesario para
--   1) Pedidos con pago/entrega separados + cancelado aparte
--   2) Clientes exclusivos con descuento %
--   3) Cuenta corriente (fiado)
--   4) Gastos de proveedores y servicios
--   5) Vincular las ventas de Caja a un cliente registrado
--
-- Cómo correrla: importar este archivo en la base de datos de
-- BrainSuplementos, igual que las migraciones anteriores. Si te tira
-- error de "columna duplicada" o "la tabla ya existe" en algún bloque, es
-- porque esa parte ya se había corrido antes — está bien, seguí con el
-- resto (podés correr el archivo de nuevo entero las veces que haga
-- falta, cada bloque se puede repetir sin romper nada salvo el que ya
-- se aplicó, que va a tirar ese error puntual y nada más).

SET NAMES utf8mb4;

-- 1) PEDIDOS: pago y entrega por separado, cancelado aparte -----------

ALTER TABLE orders
  ADD COLUMN payment_status ENUM('pendiente','pagado') NOT NULL DEFAULT 'pendiente' AFTER status,
  ADD COLUMN delivery_status ENUM('no_entregado','entregado') NOT NULL DEFAULT 'no_entregado' AFTER payment_status,
  ADD COLUMN cancelled TINYINT(1) NOT NULL DEFAULT 0 AFTER delivery_status;

-- Traduce los pedidos que ya tenías cargados al nuevo esquema:
--   pagado/enviado/entregado -> pago = pagado
--   entregado                -> entrega = entregado
--   cancelado                -> cancelado = 1
UPDATE orders SET
  payment_status = CASE WHEN status IN ('pagado','enviado','entregado') THEN 'pagado' ELSE 'pendiente' END,
  delivery_status = CASE WHEN status = 'entregado' THEN 'entregado' ELSE 'no_entregado' END,
  cancelled = CASE WHEN status = 'cancelado' THEN 1 ELSE 0 END
WHERE status IS NOT NULL;

-- Una vez migrados los datos de arriba, la columna vieja ya no hace
-- falta (todo el código nuevo usa payment_status/delivery_status/cancelled).
ALTER TABLE orders DROP COLUMN status;

-- 2) CLIENTES EXCLUSIVOS -------------------------------------------------

ALTER TABLE customers
  ADD COLUMN is_exclusive TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN discount_percent DECIMAL(5,2);

-- 3) CAJA: vincular una venta a un cliente registrado ---------------------

ALTER TABLE pos_sales
  ADD COLUMN customer_id INT AFTER cash_register_id,
  ADD CONSTRAINT fk_pos_sales_customer FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL;

-- 4) CUENTA CORRIENTE (fiado) ---------------------------------------------

CREATE TABLE IF NOT EXISTS account_movements (
  id INT AUTO_INCREMENT PRIMARY KEY,
  customer_id INT NOT NULL,
  movement_type ENUM('cargo','pago') NOT NULL,
  amount DECIMAL(10,2) NOT NULL CHECK (amount > 0),
  description VARCHAR(255),
  pos_sale_id INT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
  FOREIGN KEY (pos_sale_id) REFERENCES pos_sales(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 5) GASTOS: proveedores y servicios --------------------------------------

CREATE TABLE IF NOT EXISTS business_expenses (
  id INT AUTO_INCREMENT PRIMARY KEY,
  expense_type ENUM('proveedor','servicio') NOT NULL,
  provider_name VARCHAR(150),
  service_category VARCHAR(60),
  description VARCHAR(255),
  amount DECIMAL(10,2) NOT NULL CHECK (amount >= 0),
  expense_date DATE NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS business_expense_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  expense_id INT NOT NULL,
  product_id INT,
  product_name VARCHAR(150) NOT NULL,
  qty INT NOT NULL CHECK (qty > 0),
  unit_cost DECIMAL(10,2) NOT NULL CHECK (unit_cost >= 0),
  FOREIGN KEY (expense_id) REFERENCES business_expenses(id) ON DELETE CASCADE,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
) ENGINE=InnoDB;
