# 数据库使用说明

## 文件说明

- **`arb_master.db`** — 正式数据库（你自己的，不要上传到 GitHub）
- **`arb_master_share.db`** — 分享给别人的脱敏数据库（上传到 GitHub）

## 新用户如何使用

从 GitHub 下载 `arb_master_share.db` 后，需要重命名为 `arb_master.db`：

```bash
# 方法1：重命名文件
mv arb_master_share.db arb_master.db

# 方法2：复制
cp arb_master_share.db arb_master.db
```

## 注意事项

1. 分享数据库是脱敏版本，不包含你的真实交易数据
2. 分享数据库包含完整的表结构（含 `idx_code`、`idx_name` 列）
3. 首次运行会自动补齐缺失的列，无需手动操作
4. 你的正式数据库 `arb_master.db` 永远不要上传到 GitHub
