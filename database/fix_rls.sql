-- Script para desabilitar RLS e permitir que o bot funcione sem restrições de permissão
-- Execute isso no Editor de SQL do Supabase

ALTER TABLE users DISABLE ROW LEVEL SECURITY;
ALTER TABLE operacoes_dia DISABLE ROW LEVEL SECURITY;
ALTER TABLE eventos DISABLE ROW LEVEL SECURITY;
ALTER TABLE apps DISABLE ROW LEVEL SECURITY;

-- Opcional: Garantir que o bot possa inserir dados mesmo se o RLS for reativado por engano
-- CREATE POLICY "Permitir tudo para anon" ON users FOR ALL USING (true) WITH CHECK (true);
