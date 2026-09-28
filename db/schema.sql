-- =============================================================
-- BRAIN SUPLEMENTOS — esquema de base de datos
-- Adaptado desde la tienda de ropa (Vua Showroom) a una tienda de
-- suplementos deportivos + sistema de gestion de local.
--
-- CAMBIOS PRINCIPALES respecto de la version de ropa:
--   * Las categorias YA NO son un ENUM fijo: ahora es la tabla
--     `categories`, administrable desde /admin (alta/edicion/borrado/
--     orden), para que puedan cargar Proteinas, Creatina, Aminoacidos,
--     Barritas, Colageno, etc. sin tocar codigo.
--   * `product_colors` / `product_sizes` (colores y talles de ropa)
--     pasan a ser `product_flavors` / `product_weights` (sabores y
--     pesos/presentaciones de cada suplemento). Mismo mecanismo de
--     siempre: si un producto no tiene filas ahi, se vende con su
--     stock normal (products.stock).
--   * Los "conjuntos" (product_sets) se mantienen tal cual por dentro
--     (es una tabla generica que ya servia para armar combos de
--     productos existentes) — en el panel y la web se van a mostrar
--     como "Combos".
--   * Se agrega `brand` (marca) a products, util para un catalogo de
--     suplementos con varias marcas (Optimum, ENA, Star Nutrition, etc).
-- =============================================================

CREATE DATABASE IF NOT EXISTS brainsuplementos
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE brainsuplementos;

-- ---------------------------------------------------------
-- TABLA: admins (usuarios que pueden entrar al panel /admin)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS admins (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(150) NOT NULL,
  email VARCHAR(150) NOT NULL UNIQUE,
  username VARCHAR(80) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  security_question VARCHAR(255) NOT NULL,
  security_answer_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: categories (categorias del catalogo, ej: Proteinas, Creatina,
-- Barritas, Aminoacidos, Colageno...). Se administran desde
-- /admin/categorias: se pueden crear, editar, pausar, borrar y
-- ordenar libremente, no estan fijas en el codigo.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS categories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  slug VARCHAR(80) NOT NULL,       -- version sin espacios/acentos, para URLs y filtros
  icon VARCHAR(10),                -- opcional: un emoji para mostrar si todavia no hay foto cargada
  image_url VARCHAR(500),          -- opcional: foto de la categoria para la tarjeta de "Compra por categoria"
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_categories_slug (slug)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: subcategories (subtipos dentro de cada categoria, ej: "Whey"
-- e "Isolate" dentro de Proteinas). Se administran desde
-- /admin/subcategorias.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS subcategories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  category_id INT NOT NULL,
  name VARCHAR(60) NOT NULL,
  slug VARCHAR(60) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
  UNIQUE KEY uq_subcategories_category_slug (category_id, slug)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: products (catalogo)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(150) NOT NULL,
  category_id INT NOT NULL,
  subcategory_id INT NULL,
  brand VARCHAR(80) NULL,                 -- marca del suplemento (opcional)
  price DECIMAL(10,2) NOT NULL CHECK (price >= 0),
  discount_percent DECIMAL(5,2) NULL,     -- si tiene valor (1 a 99), es el % off sobre price
  cost_price DECIMAL(10,2) NULL,          -- precio de costo (opcional): ganancia real en Caja/Reportes
  barcode VARCHAR(64) NULL,               -- codigo de barras/SKU (opcional): para escanear en Caja
  stock INT NOT NULL DEFAULT 0,
  image_url VARCHAR(500),
  description TEXT,
  active TINYINT(1) NOT NULL DEFAULT 1,
  show_low_stock_badge TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (category_id) REFERENCES categories(id),
  FOREIGN KEY (subcategory_id) REFERENCES subcategories(id) ON DELETE SET NULL,
  INDEX idx_products_category (category_id),
  INDEX idx_products_active (active),
  UNIQUE KEY uq_products_barcode (barcode)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: product_flavors (sabores de un producto, ej: Chocolate,
-- Vainilla, Frutilla...). Si un producto no tiene filas aca, se vende
-- con su stock normal (products.stock). flavor_color_hex es solo para
-- pintar una etiqueta/chip de color en la web (no tiene que ser el
-- color real del sabor).
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_flavors (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  flavor_name VARCHAR(60) NOT NULL,
  flavor_color_hex VARCHAR(7) NOT NULL DEFAULT '#cccccc',
  stock INT NOT NULL DEFAULT 0,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: product_flavor_images (galeria de fotos de cada sabor)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_flavor_images (
  id INT AUTO_INCREMENT PRIMARY KEY,
  flavor_id INT NOT NULL,
  image_url VARCHAR(500) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (flavor_id) REFERENCES product_flavors(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: product_images (fotos extra de un producto en general,
-- independiente de los sabores)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_images (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  image_url VARCHAR(500) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: product_weights (peso/presentacion de un producto, ej: 500g,
-- 1kg, 2kg, "30 servicios", "60 capsulas"...). product_flavor_id
-- opcional: si el peso pertenece a un sabor puntual, va el id de ese
-- sabor y el stock es el de esa combinacion sabor+peso exacta.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_weights (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  product_flavor_id INT NULL,
  weight_label VARCHAR(30) NOT NULL,
  stock INT NOT NULL DEFAULT 0,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  FOREIGN KEY (product_flavor_id) REFERENCES product_flavors(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: hero_slides (imagenes del carrusel de portada)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS hero_slides (
  id INT AUTO_INCREMENT PRIMARY KEY,
  image_url VARCHAR(500) NOT NULL,
  title VARCHAR(150),
  subtitle VARCHAR(255),
  button_text VARCHAR(60),
  button_link VARCHAR(255),
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: goal_banners (imágenes motivacionales tipo "Ganar masa
-- muscular" / "Mejorar rendimiento" que llevan a los productos de esa
-- categoría — se cargan desde /admin/banners)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS goal_banners (
  id INT AUTO_INCREMENT PRIMARY KEY,
  image_url VARCHAR(500) NOT NULL,
  title VARCHAR(150) NOT NULL,
  button_link VARCHAR(255),
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: brands (logos de "Marcas con las que trabajamos", franja
-- animada en la home — se cargan desde /admin/marcas)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS brands (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  image_url VARCHAR(500) NOT NULL,
  link VARCHAR(255),
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: instagram_posts (capturas reales de posteos/reels del
-- Instagram de la marca, para la tira "Seguinos en Instagram" de la
-- home — se cargan desde /admin/instagram). El link de cada posteo es
-- opcional: si lo dejan vacío, al tocarlo lleva al perfil general
-- (INSTAGRAM_URL en caro.js).
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS instagram_posts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  image_url VARCHAR(500) NOT NULL,
  link VARCHAR(255),
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: featured_products (elegidos a mano por el admin para
-- aparecer fijos en "Novedades" o en "Más vendidos" desde
-- /admin/destacados). Los que no están fijados a mano se siguen
-- completando solos: en Novedades por fecha de carga, en Más
-- vendidos por ventas reales — ver /api/newest-products y
-- /api/most-purchased en app.py.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS featured_products (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  section ENUM('novedades','vendidos') NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  UNIQUE KEY uq_featured_product_section (product_id, section)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: customers (clientes con cuenta propia para comprar)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(150) NOT NULL,
  phone VARCHAR(30),
  email VARCHAR(150) UNIQUE,
  address VARCHAR(255),
  password_hash VARCHAR(255),
  auth_provider ENUM('local','google','apple') NOT NULL DEFAULT 'local',
  oauth_id VARCHAR(255),
  reset_token VARCHAR(100),
  reset_token_expires DATETIME,
  -- Clientes exclusivos (ej: atletas sponsoreados): se les puede cargar un
  -- % de descuento fijo que se aplica solo (automático) cuando se los
  -- elige en una venta de Caja.
  is_exclusive TINYINT(1) NOT NULL DEFAULT 0,
  discount_percent DECIMAL(5,2),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_customers_oauth (auth_provider, oauth_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: orders (pedidos online)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  customer_id INT NOT NULL,
  -- El pago y la entrega son dos cosas independientes (un pedido puede
  -- estar pagado pero no entregado todavía, por ejemplo), y "cancelado" es
  -- aparte: anula el pedido sin importar en qué estaba el pago/entrega.
  payment_status ENUM('pendiente','pagado') NOT NULL DEFAULT 'pendiente',
  delivery_status ENUM('no_entregado','entregado') NOT NULL DEFAULT 'no_entregado',
  cancelled TINYINT(1) NOT NULL DEFAULT 0,
  total DECIMAL(10,2) NOT NULL CHECK (total >= 0),
  payment_method VARCHAR(50),
  delivery_method VARCHAR(50),
  delivery_address VARCHAR(255),
  mp_preference_id VARCHAR(100),
  mp_payment_id VARCHAR(100),
  coupon_code VARCHAR(40),
  discount_amount DECIMAL(10,2),
  shipping_zone VARCHAR(100),
  shipping_cost DECIMAL(10,2),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (customer_id) REFERENCES customers(id),
  INDEX idx_orders_created_at (created_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: order_items (detalle de cada pedido)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_id INT NOT NULL,
  product_id INT,
  product_name VARCHAR(150) NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  qty INT NOT NULL CHECK (qty > 0),
  product_flavor_id INT,
  flavor_name VARCHAR(60),
  product_weight_id INT,
  weight_label VARCHAR(30),
  FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
  FOREIGN KEY (product_flavor_id) REFERENCES product_flavors(id) ON DELETE SET NULL,
  FOREIGN KEY (product_weight_id) REFERENCES product_weights(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: payment_settings (fila unica: medios de pago activos)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS payment_settings (
  id INT PRIMARY KEY DEFAULT 1,
  efectivo TINYINT(1) NOT NULL DEFAULT 1,
  transferencia TINYINT(1) NOT NULL DEFAULT 1,
  tarjeta_credito TINYINT(1) NOT NULL DEFAULT 1,
  tarjeta_debito TINYINT(1) NOT NULL DEFAULT 1,
  mercado_pago TINYINT(1) NOT NULL DEFAULT 1,
  tarjetas_aceptadas VARCHAR(255),
  -- % que se le suma al precio de efectivo/transferencia para mostrar el
  -- precio "simulado" en 3 cuotas con Mercado Pago (ej: 20 = +20%). Es
  -- solo para el cartelito de la tienda (precio de efectivo grande +
  -- "3 cuotas de $X" chiquito abajo) — no cambia lo que se cobra de
  -- verdad en el checkout con tarjeta, que lo calcula Mercado Pago.
  recargo_cuotas_pct DECIMAL(5,2) NOT NULL DEFAULT 0
) ENGINE=InnoDB;
INSERT IGNORE INTO payment_settings (id) VALUES (1);

-- ---------------------------------------------------------
-- TABLA: product_sets (COMBOS: agrupan productos que ya existen en el
-- catalogo, para que las cargue el equipo desde /admin. Cada producto
-- del combo mantiene su propio precio y stock; discount_price es un
-- precio especial opcional para todo el combo junto).
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_sets (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(150) NOT NULL,
  description VARCHAR(255),
  image_url VARCHAR(500),
  discount_price DECIMAL(10,2),
  active TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: product_set_items (que productos forman cada combo)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_set_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  set_id INT NOT NULL,
  product_id INT NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  FOREIGN KEY (set_id) REFERENCES product_sets(id) ON DELETE CASCADE,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  UNIQUE KEY uq_set_product (set_id, product_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: product_reviews (resenas de clientes)
-- ---------------------------------------------------------
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

-- ---------------------------------------------------------
-- TABLA: coupons (cupones de descuento en el checkout)
-- ---------------------------------------------------------
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

-- ---------------------------------------------------------
-- TABLA: welcome_signups (popup de bienvenida: nombre/mail/cumple
-- a cambio de un cupón de descuento en la primera compra)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS welcome_signups (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(150) NOT NULL,
  email VARCHAR(150) NOT NULL,
  birthday DATE,
  coupon_code VARCHAR(40),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_welcome_email (email)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: stock_notify_requests ("Avisame cuando haya stock")
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_notify_requests (
  id INT AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(150) NOT NULL,
  product_id INT NOT NULL,
  product_flavor_id INT,
  product_weight_id INT,
  notified TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  FOREIGN KEY (product_flavor_id) REFERENCES product_flavors(id) ON DELETE CASCADE,
  FOREIGN KEY (product_weight_id) REFERENCES product_weights(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: shipping_zones (costo de envio por zona)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS shipping_zones (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  price DECIMAL(10,2) NOT NULL DEFAULT 0,
  free_from DECIMAL(10,2),
  active TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: cash_registers (apertura/cierre de caja del local)
-- ---------------------------------------------------------
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

-- ---------------------------------------------------------
-- TABLA: pos_sales (ventas presenciales del local)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS pos_sales (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cash_register_id INT NOT NULL,
  total DECIMAL(10,2) NOT NULL,
  payment_method VARCHAR(50) NOT NULL DEFAULT 'Efectivo',
  customer_name VARCHAR(150),
  -- Si la venta se vinculó a un cliente registrado (para aplicarle su
  -- descuento de exclusivo, o para que quede en su cuenta corriente si
  -- payment_method = 'Cuenta corriente'). Puede ser NULL: sigue andando
  -- una venta a un cliente ocasional con solo el nombre en texto libre.
  customer_id INT,
  status ENUM('completada','cancelada') NOT NULL DEFAULT 'completada',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (cash_register_id) REFERENCES cash_registers(id),
  FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: pos_sale_items (detalle de cada venta presencial)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS pos_sale_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  sale_id INT NOT NULL,
  product_id INT,
  product_name VARCHAR(150) NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  qty INT NOT NULL CHECK (qty > 0),
  product_flavor_id INT,
  flavor_name VARCHAR(60),
  product_weight_id INT,
  weight_label VARCHAR(30),
  FOREIGN KEY (sale_id) REFERENCES pos_sales(id) ON DELETE CASCADE,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
  FOREIGN KEY (product_flavor_id) REFERENCES product_flavors(id) ON DELETE SET NULL,
  FOREIGN KEY (product_weight_id) REFERENCES product_weights(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: cash_expenses (gastos: proveedores, servicios, sueldos, etc)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS cash_expenses (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cash_register_id INT,
  category VARCHAR(60) NOT NULL DEFAULT 'Otro',
  description VARCHAR(255),
  amount DECIMAL(10,2) NOT NULL CHECK (amount >= 0),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (cash_register_id) REFERENCES cash_registers(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: account_movements (cuenta corriente / fiado)
-- Un cliente puede tener cargos (le fiamos algo, sube la deuda) y pagos
-- (nos pagó, baja la deuda). El saldo es SUM(cargo) - SUM(pago). Si un
-- cargo vino de una venta de Caja con medio de pago "Cuenta corriente",
-- pos_sale_id la vincula a esa venta puntual.
-- ---------------------------------------------------------
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

-- ---------------------------------------------------------
-- TABLAS: business_expenses / business_expense_items (Gastos)
-- Dos tipos de gasto del negocio (separados de los gastos chicos del día
-- a día que se cargan desde Caja, esos siguen en cash_expenses):
--   'proveedor' = una compra de mercadería a un proveedor. El monto total
--     es lo único obligatorio; las líneas de business_expense_items son
--     opcionales, para cuando se quiere desglosar qué productos vinieron
--     en esa compra (y de paso, si se elige un producto real del
--     catálogo, actualizarle el costo).
--   'servicio' = gastos fijos del local (alquiler, luz, wifi, sueldos,
--     etc), sin desglose de productos.
-- ---------------------------------------------------------
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

-- =============================================================
-- DATOS INICIALES: categorias tipicas de una tienda de suplementos.
-- Se pueden editar, renombrar, pausar, borrar o agregar mas desde
-- /admin/categorias en cualquier momento.
-- =============================================================
INSERT IGNORE INTO categories (name, slug, icon, sort_order) VALUES
('Proteínas', 'proteinas', '🥛', 1),
('Creatina', 'creatina', '💪', 2),
('Aminoácidos', 'aminoacidos', '🧬', 3),
('Pre-entreno', 'pre-entreno', '⚡', 4),
('Barritas y snacks', 'barritas-snacks', '🍫', 5),
('Colágeno', 'colageno', '✨', 6),
('Vitaminas y minerales', 'vitaminas-minerales', '💊', 7),
('Quemadores', 'quemadores', '🔥', 8),
('Accesorios', 'accesorios', '🥤', 9);

-- Subcategorias de ejemplo (opcional, se pueden borrar o agregar más)
INSERT IGNORE INTO subcategories (category_id, name, slug, sort_order)
SELECT id, 'Whey / Concentrada', 'whey', 1 FROM categories WHERE slug='proteinas'
UNION ALL SELECT id, 'Isolate', 'isolate', 2 FROM categories WHERE slug='proteinas'
UNION ALL SELECT id, 'Vegana', 'vegana', 3 FROM categories WHERE slug='proteinas'
UNION ALL SELECT id, 'Monohidratada', 'monohidratada', 1 FROM categories WHERE slug='creatina'
UNION ALL SELECT id, 'Micronizada', 'micronizada', 2 FROM categories WHERE slug='creatina'
UNION ALL SELECT id, 'BCAA', 'bcaa', 1 FROM categories WHERE slug='aminoacidos'
UNION ALL SELECT id, 'Glutamina', 'glutamina', 2 FROM categories WHERE slug='aminoacidos';

-- =============================================================
-- PRODUCTOS DE EJEMPLO (para ver la tienda funcionando desde el
-- principio). Se editan o borran desde /admin una vez que carguen
-- el catálogo real.
-- =============================================================
INSERT INTO products (name, category_id, brand, price, stock, image_url, description)
SELECT 'Proteína Whey Gold', id, 'BrainSuplementos', 24999, 20,
  'https://placehold.co/400x500/12306b/ffffff?text=Whey+Protein',
  'Proteína de suero concentrada, 24g de proteína por porción.' FROM categories WHERE slug='proteinas'
UNION ALL
SELECT 'Proteína Vegana Plant Power', id, 'BrainSuplementos', 22999, 15,
  'https://placehold.co/400x500/12306b/ffffff?text=Vegan+Protein',
  'Proteína vegetal en base a arveja y arroz, sin lactosa.' FROM categories WHERE slug='proteinas'
UNION ALL
SELECT 'Creatina Monohidratada 100%', id, 'BrainSuplementos', 12999, 30,
  'https://placehold.co/400x500/12306b/ffffff?text=Creatina',
  'Creatina monohidratada pura, aumenta fuerza y rendimiento.' FROM categories WHERE slug='creatina'
UNION ALL
SELECT 'Pre-entreno Explosive Pump', id, 'BrainSuplementos', 15999, 18,
  'https://placehold.co/400x500/12306b/ffffff?text=Pre-Entreno',
  'Energía, foco y bombeo muscular antes de entrenar.' FROM categories WHERE slug='pre-entreno'
UNION ALL
SELECT 'BCAA 2:1:1', id, 'BrainSuplementos', 13999, 22,
  'https://placehold.co/400x500/12306b/ffffff?text=BCAA',
  'Aminoácidos esenciales para recuperación muscular.' FROM categories WHERE slug='aminoacidos'
UNION ALL
SELECT 'Glutamina Pura', id, 'BrainSuplementos', 10999, 25,
  'https://placehold.co/400x500/12306b/ffffff?text=Glutamina',
  'Favorece la recuperación y el sistema inmune.' FROM categories WHERE slug='aminoacidos'
UNION ALL
SELECT 'Barrita Proteica x1', id, 'BrainSuplementos', 1999, 60,
  'https://placehold.co/400x500/12306b/ffffff?text=Barrita',
  'Barrita proteica ideal para después de entrenar.' FROM categories WHERE slug='barritas-snacks'
UNION ALL
SELECT 'Colágeno Hidrolizado + Vitamina C', id, 'BrainSuplementos', 16999, 12,
  'https://placehold.co/400x500/12306b/ffffff?text=Colageno',
  'Cuidado de piel, articulaciones y tendones.' FROM categories WHERE slug='colageno'
UNION ALL
SELECT 'Multivitamínico Daily', id, 'BrainSuplementos', 8999, 30,
  'https://placehold.co/400x500/12306b/ffffff?text=Multivitaminico',
  'Complejo de vitaminas y minerales para el día a día.' FROM categories WHERE slug='vitaminas-minerales'
UNION ALL
SELECT 'Quemador L-Carnitina', id, 'BrainSuplementos', 14999, 20,
  'https://placehold.co/400x500/12306b/ffffff?text=L-Carnitina',
  'Apoya la utilización de grasa como energía.' FROM categories WHERE slug='quemadores'
UNION ALL
SELECT 'Shaker BrainSuplementos 600ml', id, 'BrainSuplementos', 6999, 40,
  'https://placehold.co/400x500/e63b30/ffffff?text=Shaker',
  'Vaso mezclador con rejilla, 600ml.' FROM categories WHERE slug='accesorios';

-- Sabores de ejemplo (Whey Gold y Barrita Proteica)
INSERT INTO product_flavors (product_id, flavor_name, flavor_color_hex, stock, sort_order)
SELECT id, 'Chocolate', '#5b3a29', 8, 1 FROM products WHERE name='Proteína Whey Gold'
UNION ALL SELECT id, 'Vainilla', '#e9d8a6', 7, 2 FROM products WHERE name='Proteína Whey Gold'
UNION ALL SELECT id, 'Frutilla', '#e63946', 5, 3 FROM products WHERE name='Proteína Whey Gold'
UNION ALL SELECT id, 'Chocolate', '#5b3a29', 20, 1 FROM products WHERE name='Barrita Proteica x1'
UNION ALL SELECT id, 'Coco', '#f1faee', 20, 2 FROM products WHERE name='Barrita Proteica x1'
UNION ALL SELECT id, 'Maní', '#c9a66b', 20, 3 FROM products WHERE name='Barrita Proteica x1';

-- Pesos de ejemplo por sabor (Whey Gold: 1kg / 2kg de cada sabor)
INSERT INTO product_weights (product_id, product_flavor_id, weight_label, stock, sort_order)
SELECT p.id, f.id, '1kg', 5, 1 FROM products p JOIN product_flavors f ON f.product_id=p.id AND f.flavor_name='Chocolate' WHERE p.name='Proteína Whey Gold'
UNION ALL SELECT p.id, f.id, '2kg', 3, 2 FROM products p JOIN product_flavors f ON f.product_id=p.id AND f.flavor_name='Chocolate' WHERE p.name='Proteína Whey Gold'
UNION ALL SELECT p.id, f.id, '1kg', 4, 1 FROM products p JOIN product_flavors f ON f.product_id=p.id AND f.flavor_name='Vainilla' WHERE p.name='Proteína Whey Gold'
UNION ALL SELECT p.id, f.id, '2kg', 3, 2 FROM products p JOIN product_flavors f ON f.product_id=p.id AND f.flavor_name='Vainilla' WHERE p.name='Proteína Whey Gold'
UNION ALL SELECT p.id, f.id, '1kg', 5, 1 FROM products p JOIN product_flavors f ON f.product_id=p.id AND f.flavor_name='Frutilla' WHERE p.name='Proteína Whey Gold';

-- Pesos de ejemplo sin sabor (Creatina)
INSERT INTO product_weights (product_id, weight_label, stock, sort_order)
SELECT id, '300g', 15, 1 FROM products WHERE name='Creatina Monohidratada 100%'
UNION ALL SELECT id, '500g', 10, 2 FROM products WHERE name='Creatina Monohidratada 100%'
UNION ALL SELECT id, '1kg', 5, 3 FROM products WHERE name='Creatina Monohidratada 100%';

-- Combo de ejemplo (se administran desde /admin como "Combos")
INSERT INTO product_sets (name, description, discount_price, active, sort_order) VALUES
('Combo Iniciación Gym', 'Proteína + Creatina + Shaker para arrancar', 39999, 1, 1);

INSERT INTO product_set_items (set_id, product_id, sort_order)
SELECT ps.id, p.id, 1 FROM product_sets ps, products p WHERE ps.name='Combo Iniciación Gym' AND p.name='Proteína Whey Gold'
UNION ALL SELECT ps.id, p.id, 2 FROM product_sets ps, products p WHERE ps.name='Combo Iniciación Gym' AND p.name='Creatina Monohidratada 100%'
UNION ALL SELECT ps.id, p.id, 3 FROM product_sets ps, products p WHERE ps.name='Combo Iniciación Gym' AND p.name='Shaker BrainSuplementos 600ml';
