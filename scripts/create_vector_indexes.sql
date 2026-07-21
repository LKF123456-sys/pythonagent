-- pgvector IVFFlat 索引创建脚本
-- 仅在数据量足够（> 1000 行）后执行，否则 IVFFlat 性能不佳
-- 
-- 用法：
--   docker exec -i agent-db psql -U agent -d agent < scripts/create_vector_indexes.sql
--
-- 注意：IVFFlat 需要足够的数据行才能正确构建聚类，
-- 空表或少量数据时创建索引会失败或产生无效索引。

-- 长期记忆向量索引（cosine 距离，100 个聚类列表）
CREATE INDEX IF NOT EXISTS idx_ltm_embedding
    ON long_term_memories USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- RAG 文档块向量索引（cosine 距离，100 个聚类列表）
CREATE INDEX IF NOT EXISTS idx_rag_embedding
    ON rag_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- 验证索引是否创建成功
SELECT indexname, indexdef
FROM pg_indexes
WHERE indexname IN ('idx_ltm_embedding', 'idx_rag_embedding');
