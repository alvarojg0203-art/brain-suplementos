-- Migración: agrega la columna recargo_cuotas_pct a payment_settings.
-- Es el % que se le suma al precio de efectivo/transferencia para armar
-- el precio "simulado" en 3 cuotas con Mercado Pago que se muestra en la
-- tienda (precio de efectivo grande y destacado + "3 cuotas de $X"
-- chiquito abajo). Se define una sola vez desde /admin/pagos y se aplica
-- a todos los productos — no hace falta cargarlo producto por producto.
--
-- Ojo: esto es solo para el cartel informativo de la tienda. No cambia lo
-- que se cobra de verdad en un pago con tarjeta, que lo calcula Mercado
-- Pago en su propio checkout.
--
-- Cómo correrla: importar este archivo en la base de datos de
-- BrainSuplementos (igual que las migraciones anteriores). Si te tira
-- error de "columna duplicada", es porque ya se agregó antes — está bien,
-- no hace falta correrla de nuevo.

SET NAMES utf8mb4;

ALTER TABLE payment_settings
  ADD COLUMN recargo_cuotas_pct DECIMAL(5,2) NOT NULL DEFAULT 0;
