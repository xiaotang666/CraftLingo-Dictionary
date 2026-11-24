# CraftLingo-Dictionary

方块译匠 · CraftLingo 的**增强词典数据仓库**：存放词典构建脚本、自有汉化库占位与每周自动构建工作流，不存放应用源码。

工具本体与版本更新在 [xiaotang666/CraftLingo](https://github.com/xiaotang666/CraftLingo)。

## 内容

- `manifest.json`：客户端读取的词典清单（每周构建后自动更新到 `main`）
- Release 资产：`full-<日期>.db.zst` 全量词典、`inc-<基准>-<日期>.sql.zst` 增量、`manifest.json`
- `build_dict.py`：词典合并与打包脚本
- `sources/own-dict.json`：自有汉化库（格式同 VM 的 `Dict.json`，当前为空占位）
- `.github/workflows/build-dict.yml`：每周一 00:00（北京时间）自动构建

## 客户端地址

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
python build_dict.py --vm-dict vm/Dict.json --own-dict sources/own-dict.json \
    --out dist --tag 2026-11-23 \
    --base-url "https://github.com/xiaotang666/CraftLingo-Dictionary/releases/download/2026-11-23"
```

## 许可证

词典数据来自 [VM-Chinese-translate-group/i18n-Dict-Extender](https://github.com/VM-Chinese-translate-group/i18n-Dict-Extender) 与 [CFPATools/i18n-dict](https://github.com/CFPATools/i18n-dict)，遵循 **CC BY-NC-SA 4.0**，禁止商业使用，转载需署名并以相同协议共享。
