-- Migración opcional: borra la categoría de ejemplo "Ropa deportiva" y el
-- producto de ejemplo "Remera BrainSuplementos Dry-Fit" que venían
-- cargados de fábrica (quedaron de cuando esto era una tienda de ropa).
-- Si ya los habías borrado a mano desde /admin, no pasa nada al correr esto:
-- simplemente no encuentra nada para borrar.
--
-- Cómo correrla: importar este archivo en la base de datos de
-- BrainSuplementos, igual que las migraciones anteriores.

SET NAMES utf8mb4;

DELETE FROM products
WHERE category_id IN (SELECT id FROM categories WHERE slug = 'ropa-deportiva')
  AND name = 'Remera BrainSuplementos Dry-Fit';

DELETE FROM categories WHERE slug = 'ropa-deportiva';
