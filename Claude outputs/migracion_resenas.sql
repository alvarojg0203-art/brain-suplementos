-- Migración: agrega la tabla product_reviews, necesaria para que los
-- clientes puedan dejar reseñas (calificación + comentario) en la ficha
-- de cada producto. Si esta tabla no existe todavía en tu base, el
-- formulario de reseña puede no aparecer o fallar al publicar.
--
-- Cómo correrla: importar este archivo en la base de datos de
-- BrainSuplementos (igual que las migraciones anteriores).

SET NAMES utf8mb4;

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
