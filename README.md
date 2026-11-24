# CraftLingo-Dictionary

方块译匠 · CraftLingo 的**增强词典数据仓库**：存放词典构建脚本、自有汉化库占位与每周自动构建工作流，不存放应用源码。

工具本体与版本更新在 [xiaotang666/CraftLingo](https://github.com/xiaotang666/CraftLingo)。

## 内容

- `manifest.json`：客户端读取的词典清单（每周构建后自动更新到 `main`）
- Release 资产：`full-<日期>.db.zst` 全量词典、`inc-<基准>-<日期>.sql.zst` 增量、`manifest.json`
- `build_dict.py`：词典合并与打包脚本
- `sources/own-dict.json`：自有汉化库的本地补充（可选，默认空）
- `.github/workflows/build-dict.yml`：每周一 00:00（北京时间）自动构建

## 自有汉化库来源

自有词典由 [xiaotang666/J20-Mcmodlanguage-Package](https://github.com/xiaotang666/J20-Mcmodlanguage-Package) 提供，构建时**只读取 `dictionary/latest/` 目录**（sparse checkout，不拉取整个仓库）：

- `dictionary/latest/`：完整词典，构建前由对方的自动化把 `pending/` 增量合并进来并清空 `pending/`
- `dictionary/pending/`：待处理暂存区，**本仓库不读取**

`latest` 目录下可以有多个文件，支持 `.json` / `.jsonl`，按文件名排序依次合并（同名条目后者覆盖前者）。条目字段兼容：

- VM 风格：`origin_name` / `trans_name`（也支持 `ORIGIN_NAME`、`originName`）
- 术语表风格：`term` / `translation`
- 纯映射：`{"原文": "译文"}`

构建时可用仓库变量覆盖来源（Settings → Variables）：

| 变量 | 默认值 |
|---|---|
| `OWN_DICT_REPO` | `xiaotang666/J20-Mcmodlanguage-Package` |
| `OWN_DICT_BRANCH` | `main` |

汉化库不可达时工作流会告警并只用 VM 词典继续构建，不会中断。

## 客户端地址

```
https://cdn.jsdelivr.net/gh/xiaotang666/CraftLingo-Dictionary@main/manifest.json
```

使用 jsDelivr 是因为 `raw.githubusercontent.com` 在部分国内网络不可达；备用地址：

```
https://raw.githubusercontent.com/xiaotang666/CraftLingo-Dictionary/main/manifest.json
```

## 合并优先级

VM 增强词典覆盖自有汉化库：同一词条以 VM 译文为准，自有库只补充 VM 没有的条目。

## 保留策略

每次构建生成 1 个全量 + 最多 9 个以旧全量为基准的增量；客户端落后不超过 3 个版本时走增量，超过或失败自动全量下载。词典 Release 一律标记为 prerelease，避免影响工具更新检查。

## 手动构建

```bash
python -m pip install zstandard
# 把汉化库的 dictionary/latest 目录准备好后可重复传 --own-dict
python build_dict.py --vm-dict vm/Dict.json \
    --own-dict ./J20-Mcmodlanguage-Package/dictionary/latest \
    --own-dict sources/own-dict.json \
    --out dist --tag 2026-11-23 \
    --base-url "https://github.com/xiaotang666/CraftLingo-Dictionary/releases/download/2026-11-23"
```

## 许可证

词典数据来自 [VM-Chinese-translate-group/i18n-Dict-Extender](https://github.com/VM-Chinese-translate-group/i18n-Dict-Extender) 与 [CFPATools/i18n-dict](https://github.com/CFPATools/i18n-dict)，遵循 **CC BY-NC-SA 4.0**，禁止商业使用，转载需署名并以相同协议共享。
