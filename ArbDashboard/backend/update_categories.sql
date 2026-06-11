-- 更新数据库中所有基金的分类，统一为5个分类
-- 执行前请先备份数据库

-- 1. 更新"QDII 欧美"（有空格）为"QDII欧美"（无空格）
UPDATE unified_fund_list SET category = 'QDII欧美' WHERE category = 'QDII 欧美';

-- 2. 更新"QDII 亚洲"（有空格）为"QDII亚洲"（无空格）
UPDATE unified_fund_list SET category = 'QDII亚洲' WHERE category = 'QDII 亚洲';

-- 3. 更新"指数LOF"为"国内LOF"
UPDATE unified_fund_list SET category = '国内LOF' WHERE category = '指数LOF';

-- 4. 更新"混合跨境"为"QDII欧美"（合并到QDII欧美）
UPDATE unified_fund_list SET category = 'QDII欧美' WHERE category = '混合跨境';

-- 5. 删除"我的自选"分类（如果存在）
UPDATE unified_fund_list SET category = 'QDII欧美' WHERE category = '我的自选';

-- 验证更新结果
SELECT category, COUNT(*) as count FROM unified_fund_list GROUP BY category;
