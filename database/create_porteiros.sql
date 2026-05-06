-- Tabela para o Mapeamento de Porteiros e Notas de Prédios
CREATE TABLE IF NOT EXISTS mapeamento_porteiros (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    rua TEXT NOT NULL,
    numero TEXT NOT NULL,
    nome_porteiro TEXT NOT NULL,
    turno TEXT,
    notas_predio TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Garante que não teremos o mesmo nome de porteiro duplicado no mesmo endereço para o mesmo usuário
    UNIQUE(user_id, rua, numero, nome_porteiro)
);

-- Índice para facilitar a busca por endereço
CREATE INDEX IF NOT EXISTS idx_porteiros_endereco ON mapeamento_porteiros (user_id, rua, numero);
